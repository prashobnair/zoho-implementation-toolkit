# Books Reconciliation (`books`)

Reconcile Books invoices against CRM deals — matched, mismatched, missing or
orphaned — with entity and currency guards a finance owner can trust.

## The problem

"Month-end: every won deal needs exactly one correct invoice in the right
entity and currency. Three deals have no invoice, one invoice sits in the US
entity instead of India, and nobody signed off." — Marigold Labs, finance ops.

## What it does

- Matches invoices to deals by reference and checks net amounts exactly.
- Flags deals with no invoice (`missing_invoice`), invoices with no deal
  (`orphan_invoice_reference`), and several invoices on one deal
  (`duplicate_invoice_reference`).
- Never matches across legal entities by name: wrong-entity invoices are
  flagged (`cross_entity_invoice`), as are unknown entities and currency
  mismatches (`entity_currency_mismatch`, `currency_mismatch`).
- Records malformed amounts per row and continues (`invalid_amount`), and
  surfaces unreviewed tax and failed sync states (`tax_not_reviewed`,
  `sync_failed`).

## Quickstart

```sh
uv run zohokit books reconcile period.json
uv run zohokit books reconcile period.json --strict
```

## How it works

The pure engine reads one offline envelope (entities, deals, invoices) and
emits findings with stable IDs plus a `ready_for_sync` flag. Render with
`--format json|table|markdown|html` and write to a file with `--out`.

## Finding codes

| Code | Severity | Meaning |
|---|---|---|
| `duplicate_or_missing_deal_id` | error | A deal ID is empty or repeats. |
| `entity_currency_mismatch` | error | The deal entity is unknown or its currency differs. |
| `invalid_amount` | error | A malformed amount; that row's amount comparisons skipped. |
| `missing_invoice` | error | A deal has no invoice. |
| `duplicate_invoice_reference` | error | Several invoices reference one deal. |
| `cross_entity_invoice` | error | An invoice sits in the wrong legal entity. |
| `currency_mismatch` | error | Invoice currency differs from the deal currency. |
| `net_amount_mismatch` | error | Invoice net differs from the deal net. |
| `tax_not_reviewed` | error | The invoice tax was not reviewed. |
| `sync_failed` | error | The invoice sync state is failed. |
| `orphan_invoice_reference` | error | An invoice references no known deal. |

## Scope & safety

> This module reconciles offline deal and invoice data: it never connects to
> Zoho, never creates invoices or journals, and never moves money. A passing
> run is a review input for sign-off — not a posting instruction.
