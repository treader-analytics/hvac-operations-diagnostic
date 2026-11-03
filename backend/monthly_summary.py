from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
FACT_PATH = ROOT / "outputs" / "completed_job_fact.csv"
OUTPUT_DIR = ROOT / "outputs"


def load_fact(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["job_date"] = pd.to_datetime(df["job_date"], errors="coerce")
    df["month"] = df["job_date"].dt.to_period("M").astype(str)
    df["callback_flag"] = df["callback"].astype(str).str.strip().str.lower().eq("yes").astype(int)
    return df


def compute_monthly_branch_service_summary(df: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        df.groupby(["month", "branch", "service_type"], as_index=False)
        .agg(
            completed_jobs=("job_id", "count"),
            net_billed_revenue=("net_billed", "sum"),
            direct_labor_cost=("labor_cost", "sum"),
            contribution_proxy=("contribution_proxy", "sum"),
            paid_hours=("paid_hours", "sum"),
            overtime_hours=("overtime_hours", "sum"),
            callback_yes=("callback_flag", "sum"),
            completed_jobs_unique=("job_id", "nunique"),
        )
        .assign(
            revenue_per_job=lambda d: d["net_billed_revenue"] / d["completed_jobs"],
            labor_cost_share_revenue=lambda d: d["direct_labor_cost"] / d["net_billed_revenue"],
            callback_rate=lambda d: d["callback_yes"] / d["completed_jobs"],
        )
    )
    return grouped


def compute_monthly_branch_summary(df: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        df.groupby(["month", "branch"], as_index=False)
        .agg(
            completed_jobs=("job_id", "count"),
            net_billed_revenue=("net_billed", "sum"),
            direct_labor_cost=("labor_cost", "sum"),
            contribution_proxy=("contribution_proxy", "sum"),
            paid_hours=("paid_hours", "sum"),
            overtime_hours=("overtime_hours", "sum"),
            callback_yes=("callback_flag", "sum"),
        )
        .assign(
            revenue_per_job=lambda d: d["net_billed_revenue"] / d["completed_jobs"],
            labor_cost_share_revenue=lambda d: d["direct_labor_cost"] / d["net_billed_revenue"],
            callback_rate=lambda d: d["callback_yes"] / d["completed_jobs"],
        )
    )
    return grouped


def compute_monthly_service_type_summary(df: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        df.groupby(["month", "service_type"], as_index=False)
        .agg(
            completed_jobs=("job_id", "count"),
            net_billed_revenue=("net_billed", "sum"),
            direct_labor_cost=("labor_cost", "sum"),
            contribution_proxy=("contribution_proxy", "sum"),
            paid_hours=("paid_hours", "sum"),
            overtime_hours=("overtime_hours", "sum"),
            callback_yes=("callback_flag", "sum"),
        )
        .assign(
            revenue_per_job=lambda d: d["net_billed_revenue"] / d["completed_jobs"],
            labor_cost_share_revenue=lambda d: d["direct_labor_cost"] / d["net_billed_revenue"],
            callback_rate=lambda d: d["callback_yes"] / d["completed_jobs"],
        )
    )
    return grouped


def service_mix_within_decomposition(branch_df: pd.DataFrame, metric_col: str, month_pair: str) -> pd.DataFrame:
    months = sorted(branch_df["month"].unique())
    if len(months) < 2:
        return pd.DataFrame()

    m1, m2 = months[0], months[1]
    m1_df = branch_df[branch_df["month"] == m1].copy()
    m2_df = branch_df[branch_df["month"] == m2].copy()
    service_types = sorted(set(m1_df["service_type"]).union(m2_df["service_type"]))

    mix_rows = []
    for service_type in service_types:
        v1 = m1_df.loc[m1_df["service_type"] == service_type, metric_col]
        v2 = m2_df.loc[m2_df["service_type"] == service_type, metric_col]
        w1 = (m1_df.loc[m1_df["service_type"] == service_type, "completed_jobs"].sum() / m1_df["completed_jobs"].sum()) if not m1_df.empty else 0.0
        w2 = (m2_df.loc[m2_df["service_type"] == service_type, "completed_jobs"].sum() / m2_df["completed_jobs"].sum()) if not m2_df.empty else 0.0

        if v1.empty and v2.empty:
            continue
        if v1.empty:
            m1_value = 0.0
        else:
            m1_value = v1.iloc[0]
        if v2.empty:
            m2_value = 0.0
        else:
            m2_value = v2.iloc[0]

        mix_rows.append(
            {
                "branch": branch_df["branch"].iloc[0],
                "month_pair": month_pair,
                "metric": metric_col,
                "service_type": service_type,
                "share_change": w2 - w1,
                "baseline_value": m1_value,
                "mix_effect": (w2 - w1) * m1_value,
                "within_effect": w2 * (m2_value - m1_value),
                "value_change": m2_value - m1_value,
            }
        )

    if not mix_rows:
        return pd.DataFrame()
    out = pd.DataFrame(mix_rows)
    out["total_change"] = out["mix_effect"] + out["within_effect"]
    return out


def compare_months(df: pd.DataFrame, months: list[str]) -> pd.DataFrame:
    summaries = []
    for branch in sorted(df["branch"].unique()):
        branch_df = df[df["branch"] == branch].copy()
        for month_pair in [(months[0], months[1]), (months[1], months[2])]:
            left_month, right_month = month_pair
            left = branch_df[branch_df["month"] == left_month]
            right = branch_df[branch_df["month"] == right_month]
            if left.empty or right.empty:
                continue

            left_total = left["completed_jobs"].sum()
            right_total = right["completed_jobs"].sum()
            left_rev = left["net_billed_revenue"].sum()
            right_rev = right["net_billed_revenue"].sum()
            left_job_rev = left_rev / left_total if left_total else 0.0
            right_job_rev = right_rev / right_total if right_total else 0.0
            left_cb = left["callback_yes"].sum() / left_total if left_total else 0.0
            right_cb = right["callback_yes"].sum() / right_total if right_total else 0.0

            for metric_name, baseline_val, current_val in [
                ("revenue_per_job", left_job_rev, right_job_rev),
                ("callback_rate", left_cb, right_cb),
            ]:
                branch_service = branch_df[branch_df["month"].isin([left_month, right_month])].copy()
                decomp = service_mix_within_decomposition(branch_service, metric_name, f"{left_month}->{right_month}")
                if decomp.empty:
                    continue
                summaries.append(
                    {
                        "branch": branch,
                        "month_pair": f"{left_month}->{right_month}",
                        "metric": metric_name,
                        "baseline": baseline_val,
                        "current": current_val,
                        "total_change": current_val - baseline_val,
                        "mix_effect": decomp["mix_effect"].sum(),
                        "within_effect": decomp["within_effect"].sum(),
                    }
                )

    return pd.DataFrame(summaries)


def print_findings(findings: pd.DataFrame) -> None:
    if findings.empty:
        print("No monthly comparison findings available.")
        return

    display = findings[["branch", "month_pair", "metric", "baseline", "current", "total_change", "mix_effect", "within_effect"]].copy()
    for col in ["baseline", "current", "total_change", "mix_effect", "within_effect"]:
        display[col] = display[col].map(lambda x: f"{x:,.4f}" if isinstance(x, float) else x)
    print("Monthly findings (service mix vs within-service changes):")
    print(display.to_string(index=False))


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fact = load_fact(FACT_PATH)
    april_to_june = fact[fact["month"].isin(["2026-04", "2026-05", "2026-06"])].copy()

    branch_service = compute_monthly_branch_service_summary(april_to_june)
    branch_summary = compute_monthly_branch_summary(april_to_june)
    service_summary = compute_monthly_service_type_summary(april_to_june)

    branch_service.to_csv(OUTPUT_DIR / "monthly_branch_service_summary.csv", index=False)
    branch_summary.to_csv(OUTPUT_DIR / "monthly_branch_summary.csv", index=False)
    service_summary.to_csv(OUTPUT_DIR / "monthly_service_type_summary.csv", index=False)

    revenue_check = branch_summary.groupby("month")["net_billed_revenue"].sum().reset_index()
    job_check = branch_summary.groupby("month")["completed_jobs"].sum().reset_index()
    fact_month = (
        fact[fact["month"].isin(["2026-04", "2026-05", "2026-06"])].groupby("month").agg(job_count=("job_id", "count"), net_billed=("net_billed", "sum"))
    )

    monthly_reconcile = revenue_check.merge(job_check, on="month").merge(fact_month, on="month", how="inner", suffixes=("_summary", "_fact"))
    monthly_reconcile["job_count_match"] = monthly_reconcile["completed_jobs"] == monthly_reconcile["job_count"]
    monthly_reconcile["revenue_match"] = monthly_reconcile["net_billed_revenue"] == monthly_reconcile["net_billed"]
    monthly_reconcile.to_csv(OUTPUT_DIR / "monthly_reconciliation_check.csv", index=False)

    if not monthly_reconcile["job_count_match"].all() or not monthly_reconcile["revenue_match"].all():
        raise AssertionError(f"Monthly reconciliation failure: {monthly_reconcile.to_dict(orient='records')}")

    findings = compare_months(branch_service, ["2026-04", "2026-05", "2026-06"])
    findings.to_csv(OUTPUT_DIR / "monthly_service_mix_findings.csv", index=False)
    print("Saved monthly summary tables to:")
    print(f"- {OUTPUT_DIR / 'monthly_branch_service_summary.csv'}")
    print(f"- {OUTPUT_DIR / 'monthly_branch_summary.csv'}")
    print(f"- {OUTPUT_DIR / 'monthly_service_type_summary.csv'}")
    print(f"- {OUTPUT_DIR / 'monthly_reconciliation_check.csv'}")
    print(f"- {OUTPUT_DIR / 'monthly_service_mix_findings.csv'}")
    print()
    print("Monthly reconciliation checks: PASS")
    print(monthly_reconcile.to_string(index=False))
    print()
    print_findings(findings)


if __name__ == "__main__":
    main()
