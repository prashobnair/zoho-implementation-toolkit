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

Month-end workbench (policy-driven, multi-org):

```sh
uv run zohokit books reconcile recon.json \
  --policy policy.yaml --entity-map entity_map.yaml --fx-rates fx_rates.csv \
  --period 2026-09 --unavailable eu-entity
uv run zohokit books reconcile recon.json --input-format recon-v2 \
  --live --profile dev-in --books-orgs in-entity,us-entity \
  --entity-map entity_map.yaml --policy policy.yaml --period 2026-09 \
  --experimental
```

The `recon.json` workbench envelope (`{deals, invoices, credit_notes?}`,
no `entities` key) auto-detects — `--input-format recon-v2` is accepted
explicitly, while the golden-output envelope stays `legacy-v1`. The live
form reads CRM Deals live through the GET-only CRM v8 reader (explicit
`fields=` list from the policy `crm_fields` mapping: `Amount`,
`Closing_Date`, `Currency`, `Account_Name`, `Billing_Plan` plus the
entity map's `crm_criteria` field; budget-capped, period-windowed) together
with Books invoices, credit notes, contacts, currencies and taxes per org
(unverified Books endpoints, so `--experimental` is required; the fixture
file path stays the offline input). One malformed org response
marks that org `source_unavailable` while the others continue.

## How it works

The pure engine reads one offline envelope (entities, deals, invoices) and
emits findings with stable IDs plus a `ready_for_sync` flag. Render with
`--format json|table|markdown|html|sarif|junit` and write to a file with `--out`.

With `--policy` (schema `schemas/books/policy.v1.json`) the v2 engine runs
instead: key strategies (`crm_deal_id_in_invoice_custom_field`,
`reference_number`, `sales_order_link`), absolute + percentage tolerance
(only the stated bounds apply — both when both are given, exact match
when neither is), staged billing summed to the deal net (`Billing_Plan`),
credit-note netting, net-only vs gross-with-tax-table comparison,
draft/void handling (both excluded by default, each with an info audit
finding), missing/unparseable dates flagged per row (`invalid_date`,
review; the row is excluded from matching), and period windowing
(`deal_closing_date` or `invoice_date`, both bounds inclusive on the
record's own calendar date).
Entity maps keep raw Books org IDs in the local profile only; reports show
`sha256:` fingerprints. An exact-match FX table converts cross-currency
amounts with `Decimal` (missing rate → `fx_rate_missing`, never guessed).

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
| `within_tolerance` | info | Matched (or summed staged) invoices sit inside both tolerance bounds. |
| `outside_tolerance` | error | One matched invoice differs from the deal net beyond tolerance. |
| `under_invoiced` | error | Staged invoices sum below the deal net beyond tolerance. |
| `over_invoiced` | error | Staged invoices sum above the deal net beyond tolerance. |
| `credit_note_unlinked` | review | A credit note links to no known invoice. |
| `fx_rate_missing` | review | No exact FX rate covers the conversion; comparison skipped, never guessed. |
| `draft_invoice_excluded` | info | A draft invoice was excluded from matching by policy. |
| `void_invoice_excluded` | info | A void/voided/cancelled invoice was excluded from matching by policy. |
| `invalid_date` | review | A missing or unparseable record date; that row is excluded from matching. |
| `source_unavailable` | error | One org's pull failed; its records are out of scope while others continue. |

## Scope & safety

> This module reconciles offline deal and invoice data: it never connects to
> Zoho, never creates invoices or journals, and never moves money. A passing
> run is a review input for sign-off — not a posting instruction.
