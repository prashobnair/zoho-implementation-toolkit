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
uv run zohokit workflow lint --rules rules.json --metadata fields.json
uv run zohokit workflow test scenarios/marigold-labs/rules/
uv run zohokit workflow draft --description "When a deal is created, assign it to the regional manager"
```

`lint` also reads the live org (read-only, unverified endpoints):
`zohokit workflow lint --live --profile dev-in --experimental --module Deals`.
`test` prints per-suite case counts plus rule/branch coverage and renders
JUnit/HTML through the standard `--format/--out` flags.

## How it works

The pure engine replays the offline rules over one offline record and emits
findings with stable IDs; the run is not ready while findings remain. Render
with `--format json|table|markdown|html|sarif|junit` and write to a file with `--out`.

The linter translates real v8 rules into the v2 language first
(`import_real`); constructs with no representation surface as
`unsupported_construct` instead of being approximated. Loop detection
walks the rule → written-fields → edit-triggered-rules graph and reports
cycles with their paths. Scenario files (`rules` + given/when/then
`cases`, with `params` expansion) run through the same deterministic
simulator; rules that never fire become `uncovered_rule` info findings.

`draft` (UC-WF-4, AI-WF-1) turns one `--description` into a single v2
rule, validates it (language schema, field allowlist, action-target
grounding — see `docs/ai.md` — confidence floor) and simulates it
immediately against `--record` (default: a small synthetic Marigold
deal), printing the full trace. `--metadata` is `{field: type}` (or
`{module: [field api_names]}` with `--module`), `--allow-targets`
is a JSON list of pre-approved action targets. Without `--ai` (or
with no provider configured) it prints `AI disabled` and abstains.
Draft only, not deployed: nothing is written anywhere except `--out`.

`lint --ai` (AI-WF-2) attaches a cited loop explanation to each
`potential_loop` finding (an `ai` block on the finding evidence, with
an "AI suggestion" badge in HTML output). Without a provider it
prints `AI disabled` and the deterministic report is unchanged.

## Finding codes

| Code | Severity | Meaning |
|---|---|---|
| `cycle_detected` | error | The trace revisited a state signature; the rule chain is reported and simulation stopped. |
| `step_limit` | error | The rule trace exceeded the step budget; the rule chain is reported. |
| `missing_owner` | error | An assign-owner action has no usable owner value. |
| `no_op_stage` | error | A set-stage action targets the stage already set. |
| `duplicate_followup` | error | The same follow-up would fire twice for one record. |
| `duplicate_side_effect` | error | A simulated call would repeat for one record, action, template/url and day. |
| `conflicting_field_updates` | error | Two rules on the same trigger update one field differently (assigning owners counts as writing `Owner`). |
| `potential_loop` | error | Rules write fields that re-trigger each other; one finding per rule group with the member rules and a representative path. |
| `stale_field_reference` | error | A rule references a field absent from the metadata. |
| `empty_rule` | warning | A rule has no actions. |
| `dead_rule` | warning | An inactive rule never fires. |
| `webhook_failing` | error | A rule webhook has recent execution failures. |
| `near_limit` | warning | Action usage is at 80%+ of the configured limit. |
| `unsupported_construct` | review | A real-rule construct has no simulator form. |
| `uncovered_rule` | info | No scenario case exercised the rule. |
| `scenario_case_failed` | error | A scenario case assertion mismatched (runner only). |

## Scope & safety

> This module simulates offline rule definitions: it never connects to Zoho,
> never creates tasks, never sends email, and only approximates trigger
> ordering. Treat the trace as a review aid, not a proof of production
> behavior.
