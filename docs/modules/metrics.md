# Metrics Contracts (`metrics`)

Define KPIs once and test them before building dashboards — joins, freshness,
audience visibility and impossible values, all checked.

## The problem

"Sales, finance and operations each quote different revenue numbers from the
same Zoho data. Joins double-count, snapshots go stale, and finance totals
leak into the sales view." — Marigold Labs, analytics owner.

## What it does

- Joins deals and invoices to accounts by explicit IDs; orphans are findings,
  never silent drops (`orphan_deal`, `orphan_invoice`).
- Excludes non-report currencies from the revenue sum instead of converting
  by a guessed rate (`currency_mismatch`).
- Enforces freshness: future snapshots error, snapshots older than 24h are
  flagged (`future_snapshot`, `stale_snapshot`).
- Deduplicates repeated deal/invoice IDs out of the aggregates
  (`duplicate_id`) and rejects impossible staff rows (`invalid_staff_row`,
  `invalid_utilization`).
- Renders per audience: finance totals and utilization never appear in the
  wrong audience's output.

## Quickstart

```sh
uv run zohokit metrics check tables.json
uv run zohokit metrics check tables.json --audience sales
```

## How it works

The pure engine evaluates one offline envelope (accounts, deals, invoices,
staff plus freshness markers) for the chosen audience and emits findings with
stable IDs. Render with `--format json|table|markdown|html` and write to a
file with `--out`.

## Finding codes

| Code | Severity | Meaning |
|---|---|---|
| `future_snapshot` | error | A source timestamp is newer than `as_of`. |
| `stale_snapshot` | error | A source timestamp is older than the 24h freshness SLA. |
| `orphan_deal` | error | A deal references an unknown account. |
| `orphan_invoice` | error | An invoice references an unknown account. |
| `currency_mismatch` | error | An invoice is not in the report currency. |
| `duplicate_id` | error | A deal/invoice ID repeats; excluded from aggregates. |
| `invalid_staff_row` | error | A staff row breaks hours validation. |
| `invalid_utilization` | error | Aggregate utilization is impossible. |

## Scope & safety

> This module checks offline tables for one audience at a time: it never
> connects to Zoho, never builds dashboards, and `--audience` is a report
> selector, not authenticated access control. Verify row-level policy in the
> real system before sharing widely.
