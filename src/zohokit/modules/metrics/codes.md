# Metrics finding codes

| Code | Severity | Meaning |
|---|---|---|
| `future_snapshot` | error | A source timestamp is newer than `as_of`. |
| `stale_snapshot` | error | A source timestamp is older than the 24h freshness SLA. |
| `orphan_deal` | error | A deal references an unknown account. |
| `orphan_invoice` | error | An invoice references an unknown account. |
| `currency_mismatch` | error | An invoice is not in the report currency. |
| `duplicate_id` | error | A deal/invoice ID repeats; excluded from aggregates (TK-FIX-3). |
| `invalid_staff_row` | error | A staff row breaks hours validation (TK-FIX-4). |
| `invalid_utilization` | error | Aggregate utilization is impossible. |
