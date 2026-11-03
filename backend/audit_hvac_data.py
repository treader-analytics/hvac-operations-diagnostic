from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

WORKBOOK_PATH = Path(__file__).resolve().parent / "data" / "Reader_Analytics_HVAC_Data_Collection.xlsx"
SQL_PATH = Path(__file__).resolve().parent / "sql" / "completed_job_fact.sql"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "outputs" / "completed_job_fact.csv"
REQUIRED_SHEETS = [
    "Customers",
    "Technicians",
    "Jobs",
    "TimeEntries",
    "Invoices",
    "MarketingSpend",
]


def load_sheets(path: Path) -> Dict[str, pd.DataFrame]:
    if not path.exists():
        raise FileNotFoundError(f"Workbook not found: {path}")

    workbook = pd.ExcelFile(path)
    missing = [sheet for sheet in REQUIRED_SHEETS if sheet not in workbook.sheet_names]
    if missing:
        raise ValueError(f"Missing required sheets: {missing}")

    sheets: Dict[str, pd.DataFrame] = {}
    for sheet in REQUIRED_SHEETS:
        df = pd.read_excel(path, sheet_name=sheet)
        df = df.copy()
        df.columns = [str(column).strip().lower() for column in df.columns]
        sheets[sheet] = df
    return sheets


def dataframe_summary(sheets: Dict[str, pd.DataFrame]) -> str:
    summary_lines = ["Workbook sheet counts:"]
    for sheet_name, df in sheets.items():
        summary_lines.append(f"- {sheet_name}: {len(df)} rows x {len(df.columns)} columns")
    return "\n".join(summary_lines)


def create_sqlite_db(sheets: Dict[str, pd.DataFrame]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    for sheet_name, df in sheets.items():
        table_name = sheet_name.lower()
        df.to_sql(table_name, conn, index=False, if_exists="replace")
    return conn


def run_rule(conn: sqlite3.Connection, rule_name: str, description: str, query: str) -> Dict[str, Any]:
    df = pd.read_sql_query(query, conn)
    violation_count = int(len(df))
    preview = df.head(5).to_dict(orient="records")
    return {
        "rule": rule_name,
        "description": description,
        "passed": violation_count == 0,
        "violation_count": violation_count,
        "preview": preview,
    }


def build_rules(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rules: List[Dict[str, Any]] = []

    rules.append(
        run_rule(
            conn,
            "customers.customer_id_unique",
            "Each customer_id must appear only once.",
            "SELECT customer_id, COUNT(*) AS row_count FROM customers GROUP BY customer_id HAVING COUNT(*) > 1 ORDER BY row_count DESC, customer_id",
        )
    )
    rules.append(
        run_rule(
            conn,
            "technicians.technician_id_unique",
            "Each technician_id must appear only once.",
            "SELECT technician_id, COUNT(*) AS row_count FROM technicians GROUP BY technician_id HAVING COUNT(*) > 1 ORDER BY row_count DESC, technician_id",
        )
    )
    rules.append(
        run_rule(
            conn,
            "jobs.job_id_unique",
            "Each job_id must appear only once.",
            "SELECT job_id, COUNT(*) AS row_count FROM jobs GROUP BY job_id HAVING COUNT(*) > 1 ORDER BY row_count DESC, job_id",
        )
    )
    rules.append(
        run_rule(
            conn,
            "timeentries.time_entry_id_unique",
            "Each time_entry_id must appear only once.",
            "SELECT time_entry_id, COUNT(*) AS row_count FROM timeentries GROUP BY time_entry_id HAVING COUNT(*) > 1 ORDER BY row_count DESC, time_entry_id",
        )
    )
    rules.append(
        run_rule(
            conn,
            "invoices.invoice_id_unique",
            "Each invoice_id must appear only once.",
            "SELECT invoice_id, COUNT(*) AS row_count FROM invoices GROUP BY invoice_id HAVING COUNT(*) > 1 ORDER BY row_count DESC, invoice_id",
        )
    )
    rules.append(
        run_rule(
            conn,
            "marketingspend.natural_key_unique",
            "The natural key (month_start, branch, channel) should be unique in MarketingSpend.",
            "SELECT month_start, branch, channel, COUNT(*) AS row_count FROM marketingspend GROUP BY month_start, branch, channel HAVING COUNT(*) > 1 ORDER BY row_count DESC, branch, channel",
        )
    )

    rules.append(
        run_rule(
            conn,
            "customers.customer_id_required",
            "customer_id values are required and cannot be blank.",
            "SELECT customer_id, customer_name, home_branch FROM customers WHERE customer_id IS NULL OR TRIM(CAST(customer_id AS TEXT)) = '' ORDER BY home_branch, customer_name",
        )
    )
    rules.append(
        run_rule(
            conn,
            "technicians.technician_id_required",
            "technician_id values are required and cannot be blank.",
            "SELECT technician_id, technician_name, home_branch FROM technicians WHERE technician_id IS NULL OR TRIM(CAST(technician_id AS TEXT)) = '' ORDER BY home_branch, technician_name",
        )
    )
    rules.append(
        run_rule(
            conn,
            "jobs.job_id_required",
            "job_id values are required and cannot be blank.",
            "SELECT job_id, customer_id, branch FROM jobs WHERE job_id IS NULL OR TRIM(CAST(job_id AS TEXT)) = '' ORDER BY branch, customer_id",
        )
    )
    rules.append(
        run_rule(
            conn,
            "timeentries.time_entry_id_required",
            "time_entry_id values are required and cannot be blank.",
            "SELECT time_entry_id, job_id, technician_id FROM timeentries WHERE time_entry_id IS NULL OR TRIM(CAST(time_entry_id AS TEXT)) = '' ORDER BY job_id, technician_id",
        )
    )
    rules.append(
        run_rule(
            conn,
            "invoices.invoice_id_required",
            "invoice_id values are required and cannot be blank.",
            "SELECT invoice_id, job_id, invoice_date FROM invoices WHERE invoice_id IS NULL OR TRIM(CAST(invoice_id AS TEXT)) = '' ORDER BY job_id, invoice_date",
        )
    )
    rules.append(
        run_rule(
            conn,
            "invoices.financial_fields_required",
            "Invoice financial fields must be populated.",
            "SELECT invoice_id, job_id, gross_charge, discount, net_billed, amount_received FROM invoices WHERE gross_charge IS NULL OR discount IS NULL OR net_billed IS NULL OR amount_received IS NULL ORDER BY job_id, invoice_id",
        )
    )
    rules.append(
        run_rule(
            conn,
            "timeentries.financial_fields_required",
            "Time-entry labor fields must be populated.",
            "SELECT time_entry_id, job_id, technician_id, paid_hours, overtime_hours FROM timeentries WHERE paid_hours IS NULL OR overtime_hours IS NULL ORDER BY job_id, technician_id",
        )
    )

    rules.append(
        run_rule(
            conn,
            "jobs.customer_id_join",
            "Each job customer_id must match a record in Customers.",
            "SELECT j.job_id, j.customer_id, j.branch FROM jobs j LEFT JOIN customers c ON c.customer_id = j.customer_id WHERE c.customer_id IS NULL ORDER BY j.branch, j.customer_id",
        )
    )
    rules.append(
        run_rule(
            conn,
            "timeentries.job_id_join",
            "Each TimeEntries.job_id must match a record in Jobs.",
            "SELECT te.time_entry_id, te.job_id, te.technician_id FROM timeentries te LEFT JOIN jobs j ON j.job_id = te.job_id WHERE j.job_id IS NULL ORDER BY te.job_id, te.technician_id",
        )
    )
    rules.append(
        run_rule(
            conn,
            "timeentries.technician_id_join",
            "Each TimeEntries.technician_id must match a record in Technicians.",
            "SELECT te.time_entry_id, te.job_id, te.technician_id FROM timeentries te LEFT JOIN technicians t ON t.technician_id = te.technician_id WHERE t.technician_id IS NULL ORDER BY te.job_id, te.technician_id",
        )
    )
    rules.append(
        run_rule(
            conn,
            "invoices.job_id_join",
            "Each invoice job_id must match a record in Jobs.",
            "SELECT i.invoice_id, i.job_id, i.invoice_date FROM invoices i LEFT JOIN jobs j ON j.job_id = i.job_id WHERE j.job_id IS NULL ORDER BY i.job_id, i.invoice_id",
        )
    )
    rules.append(
        run_rule(
            conn,
            "jobs.lead_technician_join",
            "Each Jobs.lead_technician_id must match a record in Technicians.",
            "SELECT j.job_id, j.lead_technician_id, j.branch FROM jobs j LEFT JOIN technicians t ON t.technician_id = j.lead_technician_id WHERE t.technician_id IS NULL ORDER BY j.branch, j.job_id",
        )
    )

    rules.append(
        run_rule(
            conn,
            "jobs.completed_one_invoice",
            "Every completed job must have exactly one invoice.",
            "SELECT j.job_id, j.job_status, COUNT(i.invoice_id) AS invoice_count FROM jobs j LEFT JOIN invoices i ON i.job_id = j.job_id WHERE LOWER(TRIM(CAST(j.job_status AS TEXT))) = 'completed' GROUP BY j.job_id, j.job_status HAVING COUNT(i.invoice_id) <> 1 ORDER BY j.job_id",
        )
    )
    rules.append(
        run_rule(
            conn,
            "jobs.no_invoice_for_canceled",
            "Canceled jobs must not have an invoice record.",
            "SELECT j.job_id, j.job_status, i.invoice_id FROM jobs j JOIN invoices i ON i.job_id = j.job_id WHERE LOWER(TRIM(CAST(j.job_status AS TEXT))) = 'canceled' ORDER BY j.job_id, i.invoice_id",
        )
    )
    rules.append(
        run_rule(
            conn,
            "jobs.no_time_entry_for_canceled",
            "Canceled jobs must not have any time entry records.",
            "SELECT j.job_id, j.job_status, te.time_entry_id, te.technician_id FROM jobs j JOIN timeentries te ON te.job_id = j.job_id WHERE LOWER(TRIM(CAST(j.job_status AS TEXT))) = 'canceled' ORDER BY j.job_id, te.time_entry_id",
        )
    )
    rules.append(
        run_rule(
            conn,
            "jobs.completed_has_time_entries",
            "Every completed job must have at least one time entry.",
            "SELECT j.job_id, j.job_status, COUNT(te.time_entry_id) AS time_entry_count FROM jobs j LEFT JOIN timeentries te ON te.job_id = j.job_id WHERE LOWER(TRIM(CAST(j.job_status AS TEXT))) = 'completed' GROUP BY j.job_id, j.job_status HAVING COUNT(te.time_entry_id) < 1 ORDER BY j.job_id",
        )
    )

    rules.append(
        run_rule(
            conn,
            "invoices.gross_minus_discount_equals_net",
            "For each invoice, gross_charge - discount must equal net_billed and net_billed must be present.",
            "SELECT invoice_id, job_id, gross_charge, discount, net_billed FROM invoices WHERE net_billed IS NULL OR ABS((gross_charge - discount) - net_billed) > 0.01 ORDER BY job_id, invoice_id",
        )
    )
    rules.append(
        run_rule(
            conn,
            "invoices.amount_received_not_exceed_billed",
            "amount_received must be non-negative and cannot exceed net_billed.",
            "SELECT invoice_id, job_id, net_billed, amount_received FROM invoices WHERE amount_received < 0 OR amount_received > net_billed ORDER BY job_id, invoice_id",
        )
    )
    rules.append(
        run_rule(
            conn,
            "invoices.discount_non_negative",
            "Invoice discount can never be negative.",
            "SELECT invoice_id, job_id, discount FROM invoices WHERE discount < 0 ORDER BY job_id, invoice_id",
        )
    )
    rules.append(
        run_rule(
            conn,
            "timeentries.paid_hours_non_negative",
            "paid_hours must be non-negative.",
            "SELECT time_entry_id, job_id, technician_id, paid_hours FROM timeentries WHERE paid_hours < 0 ORDER BY job_id, time_entry_id",
        )
    )
    rules.append(
        run_rule(
            conn,
            "timeentries.overtime_non_negative",
            "overtime_hours must be non-negative.",
            "SELECT time_entry_id, job_id, technician_id, overtime_hours FROM timeentries WHERE overtime_hours < 0 ORDER BY job_id, time_entry_id",
        )
    )
    rules.append(
        run_rule(
            conn,
            "timeentries.overtime_within_paid_hours",
            "overtime_hours cannot exceed paid_hours.",
            "SELECT time_entry_id, job_id, technician_id, paid_hours, overtime_hours FROM timeentries WHERE overtime_hours > paid_hours ORDER BY job_id, time_entry_id",
        )
    )

    return rules


def missing_acquisition_channels(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM customers WHERE acquisition_channel IS NULL OR TRIM(CAST(acquisition_channel AS TEXT)) = ''"
        ).fetchone()[0]
    )


def patient_copy_of_sheets(sheets: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    return {name: df.copy() for name, df in sheets.items()}


def validate_failure_cases() -> None:
    base_sheets = load_sheets(WORKBOOK_PATH)

    duplicate_invoice_sheets = patient_copy_of_sheets(base_sheets)
    invoice_row = duplicate_invoice_sheets["Invoices"].iloc[0].copy()
    invoice_row["invoice_id"] = "I99999"
    invoice_row["job_id"] = base_sheets["Invoices"].iloc[0]["job_id"]
    duplicate_invoice_sheets["Invoices"] = pd.concat(
        [duplicate_invoice_sheets["Invoices"], pd.DataFrame([invoice_row])], ignore_index=True
    )
    duplicate_invoice_rules = build_rules(create_sqlite_db(duplicate_invoice_sheets))
    duplicate_invoice_violations = [rule for rule in duplicate_invoice_rules if rule["rule"] == "jobs.completed_one_invoice"]
    assert duplicate_invoice_violations and not duplicate_invoice_violations[0]["passed"], (
        "Duplicate invoice case should fail the completed-job invoice rule."
    )

    blank_net_billed_sheets = patient_copy_of_sheets(base_sheets)
    blank_net_billed_sheets["Invoices"].loc[0, "net_billed"] = None
    blank_net_billed_rules = build_rules(create_sqlite_db(blank_net_billed_sheets))
    blank_net_billed_violations = [rule for rule in blank_net_billed_rules if rule["rule"] == "invoices.gross_minus_discount_equals_net"]
    assert blank_net_billed_violations and not blank_net_billed_violations[0]["passed"], (
        "Blank net_billed should fail the invoice reconciliation rule."
    )

    print("Self-test: failure cases behaved as expected on disposable in-memory copies.")


def print_report(sheets: Dict[str, pd.DataFrame], rules: List[Dict[str, Any]], warning_count: int) -> None:
    print("=" * 90)
    print("HVAC DATA QUALITY AUDIT REPORT")
    print("=" * 90)
    print(f"Workbook: {WORKBOOK_PATH.name}")
    print()
    print(dataframe_summary(sheets))
    print()
    print("Validation rules executed:")
    print("- Unique IDs")
    print("- Required IDs and field completeness")
    print("- Join integrity checks")
    print("- Invoice arithmetic checks")
    print("- Time-entry logic checks")
    print("- Completed-job business rules")
    print()

    if warning_count:
        print(f"WARNING: {warning_count} missing acquisition channels in Customers (known warning; does not fail the audit).")
    print()

    passed = 0
    failed = 0
    for result in rules:
        status = "PASS" if result["passed"] else "FAIL"
        if result["passed"]:
            passed += 1
        else:
            failed += 1
        print(f"[{status}] {result['rule']}: {result['description']}")
        if not result["passed"]:
            print(f"    Violations: {result['violation_count']}")
            for sample in result["preview"][:5]:
                print(f"    Example: {sample}")

    print()
    print(f"Overall result: {passed} passed, {failed} failed")
    if failed == 0:
        print("Audit status: CLEAN")
    else:
        print("Audit status: REVIEW REQUIRED")
    print("=" * 90)


def execute_completed_job_fact(conn: sqlite3.Connection) -> pd.DataFrame:
    sql = SQL_PATH.read_text(encoding="utf-8")
    result = pd.read_sql_query(sql, conn)

    required_columns = [
        "job_id",
        "customer_id",
        "branch",
        "job_date",
        "service_type",
        "day_type",
        "callback",
        "invoice_id",
        "net_billed",
        "materials_cost",
        "subcontract_cost",
        "paid_hours",
        "overtime_hours",
        "labor_cost",
        "contribution_proxy",
    ]

    missing_columns = [col for col in required_columns if col not in result.columns]
    if missing_columns:
        raise ValueError(f"Completed job result is missing required columns: {missing_columns}")

    if len(result) != 756:
        raise AssertionError(f"Completed job fact row count mismatch: expected 756 rows, found {len(result)}.")
    if result["job_id"].nunique() != 756:
        raise AssertionError(f"Completed job fact job_id uniqueness mismatch: expected 756 distinct job IDs, found {result['job_id'].nunique()}.")

    required_cost_columns = ["net_billed", "materials_cost", "subcontract_cost", "labor_cost"]
    missing_costs = [col for col in required_cost_columns if result[col].isnull().any()]
    if missing_costs:
        raise AssertionError(f"Missing required cost values detected in completed job fact: {missing_costs}")

    result_total = float(result["net_billed"].sum())
    expected_total = 1378448.0
    if not math.isclose(result_total, expected_total, abs_tol=0.01):
        raise AssertionError(
            f"Completed job fact net_billed total mismatch: expected {expected_total:.2f}, found {result_total:.2f}."
        )

    source_total = float(
        pd.read_sql_query(
            "SELECT SUM(i.net_billed) AS total_net_billed FROM jobs j JOIN invoices i ON i.job_id = j.job_id WHERE LOWER(TRIM(j.job_status)) = 'completed'",
            conn,
        )["total_net_billed"].iloc[0]
    )
    if not math.isclose(source_total, expected_total, abs_tol=0.01):
        raise AssertionError(
            f"Invoices source revenue mismatch: expected {expected_total:.2f}, found {source_total:.2f}."
        )

    if not math.isclose(result_total, source_total, abs_tol=0.01):
        raise AssertionError(
            f"Completed job fact revenue does not reconcile to source invoices: fact={result_total:.2f}, source={source_total:.2f}."
        )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_PATH, index=False)
    print(f"Completed job fact saved to: {OUTPUT_PATH}")
    print(f"Job-level checks: rows={len(result)}, distinct_job_ids={result['job_id'].nunique()}, net_billed_total={result_total:,.2f}")
    print("Source revenue reconciliation: PASS")
    print("First five rows:")
    print(result.head(5).to_string(index=False))
    return result


def main() -> None:
    sheets = load_sheets(WORKBOOK_PATH)
    conn = create_sqlite_db(sheets)

    rules = build_rules(conn)
    failed_rules = [rule for rule in rules if not rule["passed"]]
    if failed_rules:
        print_report(sheets, rules, missing_acquisition_channels(conn))
        raise SystemExit(f"Audit failed: {len(failed_rules)} required rule(s) did not pass.")

    warning_count = missing_acquisition_channels(conn)
    print_report(sheets, rules, warning_count)

    result = execute_completed_job_fact(conn)
    conn.close()
    print(f"Completed job fact output rows: {len(result)}")
    print(f"Distinct job IDs: {result['job_id'].nunique()}")


if __name__ == "__main__":
    main()
