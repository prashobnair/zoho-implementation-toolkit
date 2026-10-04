# Workflow Lint & Simulator (`workflow`)

Trace workflow rules over a record — see the exact firing order, loops and
duplicate side effects before the org runs them.

## The problem

"Two rules update the same field to different values, a follow-up fires twice
for one deal, and one rule chain loops back on itself. The org grew these
rules over years and nobody can trace what fires when." — Marigold Labs, CRM
admin.

## What it does

- Simulates rules against one record with deterministic ordering and a full
  causal trace.
- Stops at revisited state signatures (`cycle_detected`) and at the step
  budget (`step_limit`); nothing is ever executed.
- Flags owner assignments with no usable owner (`missing_owner`), stage
  actions that change nothing (`no_op_stage`), and follow-ups that would fire
  twice (`duplicate_followup`).
- Keeps a side-effect ledger so simulated emails and tasks are counted, never sent.

## Quickstart

```sh
uv run zohokit workflow simulate rules.json
uv run zohokit workflow simulate rules.json --strict
```

## How it works

The pure engine replays the offline rules over one offline record and emits
findings with stable IDs; the run is not ready while findings remain. Render
with `--format json|table|markdown|html|sarif|junit` and write to a file with `--out`.

## Finding codes

| Code | Severity | Meaning |
|---|---|---|
| `cycle_detected` | error | The trace revisited a state signature; simulation stopped. |
| `step_limit` | error | The rule trace exceeded the step budget. |
| `missing_owner` | error | An assign-owner action has no usable owner value. |
| `no_op_stage` | error | A set-stage action targets the stage already set. |
| `duplicate_followup` | error | The same follow-up would fire twice for one record. |

## Scope & safety

> This module simulates offline rule definitions: it never connects to Zoho,
> never creates tasks, never sends email, and only approximates trigger
> ordering. Treat the trace as a review aid, not a proof of production
> behavior.
