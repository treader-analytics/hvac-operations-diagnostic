-- One record per completed, invoiced HVAC job.
-- Labor-cost assumption: paid_hours includes overtime_hours;
-- overtime hours are costed at 1.5x the technician's base hourly rate.
-- Contribution proxy excludes overhead and other indirect costs.
WITH labor_by_job AS (
    SELECT
        te.job_id,
        SUM(COALESCE(te.paid_hours, 0)) AS paid_hours,
        SUM(COALESCE(te.overtime_hours, 0)) AS overtime_hours,
        SUM(
            (COALESCE(te.paid_hours, 0) - COALESCE(te.overtime_hours, 0))
                * t.base_hourly_rate
            + COALESCE(te.overtime_hours, 0) * t.base_hourly_rate * 1.5
        ) AS labor_cost
    FROM timeentries AS te
    INNER JOIN technicians AS t
        ON te.technician_id = t.technician_id
    GROUP BY te.job_id
)
SELECT
    j.job_id,
    j.customer_id,
    j.branch,
    j.job_date,
    j.service_type,
    j.day_type,
    j.callback,
    i.invoice_id,
    i.net_billed,
    i.materials_cost,
    i.subcontract_cost,
    ROUND(l.paid_hours, 2) AS paid_hours,
    ROUND(l.overtime_hours, 2) AS overtime_hours,
    ROUND(l.labor_cost, 2) AS labor_cost,
    ROUND(
        i.net_billed
        - i.materials_cost
        - i.subcontract_cost
        - l.labor_cost,
        2
    ) AS contribution_proxy
FROM jobs AS j
INNER JOIN invoices AS i
    ON j.job_id = i.job_id
INNER JOIN labor_by_job AS l
    ON j.job_id = l.job_id
WHERE LOWER(TRIM(j.job_status)) = 'completed'
ORDER BY j.job_date, j.job_id;
