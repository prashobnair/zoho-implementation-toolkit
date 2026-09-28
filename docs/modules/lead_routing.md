# Lead Routing Lab (`lead_routing`)

Route inbound leads to queues with explicit consent and duplicate handling —
and simulate first, send nothing, merge nothing.

## The problem

"Six hundred leads a month from chat, forms and calls. Which ones are
sales-ready, which lack consent, which duplicate an earlier lead — and what
changes if we tweak the routing rules?" — Marigold Labs, RevOps.

## What it does

- Qualifies only sales intent with confirmed budget and granted consent
  (`qualified_sales_inquiry`); everything else goes to a human queue with a
  reason (`consent_not_verified`, `needs_human_triage`, `budget_unconfirmed`,
  `unrecognized_intent`, `unsupported_channel`).
- Normalizes phones to strict E.164 with no region guessing by default
  (`invalid_or_missing_e164`); an explicit `--default-region` flags inferred
  numbers (`inferred_region`).
- Flags same-phone repeats as candidates (`phone_candidate_match`) — reported,
  never merged.
- Keeps `outbound_messages` at zero: routing is a decision, not a send.

## Quickstart

```sh
uv run zohokit lead-routing route leads.json
uv run zohokit lead-routing route leads.json --default-region IN
```

## How it works

The pure engine routes one offline lead list in order and emits findings with
stable IDs; the run is not ready while leads await triage. Render with
`--format json|table|markdown|html` and write to a file with `--out`.

## Finding codes

| Code | Severity | Meaning |
|---|---|---|
| `qualified_sales_inquiry` | info | Sales intent with confirmed budget and consent. |
| `consent_not_verified` | review | Consent is not granted; human queue. |
| `needs_human_triage` | review | Support/unknown intent; human queue. |
| `budget_unconfirmed` | review | Sales intent without confirmed budget; human queue. |
| `unrecognized_intent` | review | Intent is none of the known values; human queue. |
| `unsupported_channel` | review | Channel is not a known inbound channel; human queue. |
| `invalid_or_missing_e164` | review | No usable E.164 phone; human queue. |
| `phone_candidate_match` | review | E.164 matches an earlier lead; never merged. |
| `inferred_region` | info | Region came from the explicit `--default-region`. |

## Scope & safety

> This module routes offline lead data: it never connects to Zoho, never
> sends messages, never creates or updates leads, and never merges duplicates
> or infers consent. Sample phone numbers in fixtures are fictional and must
> never be contacted.
