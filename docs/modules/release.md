# Release Readiness (`release`)

Diff two configuration manifests and gate a promotion — removals, behavior
changes and missing dependencies, with a stable fingerprint.

## The problem

"Someone edited production directly again, and Friday's sandbox promotion has
dozens of changed components with no deploy order. If we remove the wrong
field, three layouts and a webhook break silently." — Marigold Labs, release
manager.

## What it does

- Diffs `before` vs `after` manifests by stable `(kind, name)` identity,
  with per-component attribute diffs (`enabled: true → false`).
- Infers dependencies (declared plus heuristic text-scan edges, labeled).
- Scores every change low/medium/high and proposes a topological deploy
  order (reverse for removals), plus a signed rollback plan.
- Snapshots an org to `config/zoho/` (one file per kind) and flags
  unapproved drift against the approved snapshot.
- Renders the gate as JSON/table/Markdown/HTML/SARIF/JUnit plus a
  PR-comment Markdown body (≤ 65,000 chars) for the GitHub Action.

## Quickstart

```sh
uv run zohokit release diff before-after.json
uv run zohokit release diff before-after.json --strict
uv run zohokit release diff before-after.json --pr-comment-out comment.md \
  --deploy-order-out order.json --rollback-plan-out rollback/
```

## How it works

The pure engine compares two offline manifests and emits findings with
stable IDs. Manifest v2 components carry `{kind, name, module, api_name,
attributes, depends_on, source_env}`; legacy v1 items (kind plus name)
keep working. Render with
`--format json|table|markdown|html|sarif|junit` and write to a file with `--out`.

## Risk scoring

| Change | Risk | Reason |
|---|---|---|
| removal of any component | high | delete first, ask later is how data is lost |
| behavior kind added or changed (workflow, validation, function, webhook) | high | automation can double-fire or loop |
| picklist value removed while records use it | high | live records reference the value |
| field type change | high | values may stop parsing or matching |
| layout-only change (layout, layout_rule, custom_button, role) | low | presentation without behavior |
| anything else added or changed | medium | needs a glance, not a rollback drill |

The release risk is the maximum per-change level.

## Finding codes

| Code | Severity | Meaning |
|---|---|---|
| `behavior_regression_review` | error | A workflow, validation, function or webhook was added or changed. |
| `removal_review` | error | A component was removed. |
| `missing_dependency` | error | A component depends on something absent from the target manifest. |
| `dependency_cycle` | error | Added/changed components depend on each other in a cycle; no safe deploy order. |
| `field_type_change` | error | A field's `data_type` changed; values may stop parsing or matching. |
| `picklist_value_in_use` | error | A removed picklist value is still referenced by records (`in_use` / `in_use_count`). |
| `unapproved_drift` | error | Live differs from the approved snapshot outside a promotion (drift mode only). |
| `irreversible_change` | review | A removal destroys stored values; restore needs a confirmed backup. |
| `experimental_kind` | warning | A component uses an unverified kind (`blueprint`, `client_script`, `profile_permission`). |
| `heuristic_dependency` | info | A text scan suggests one component uses another; labeled, never blocking. |

## Scope & safety

> This module diffs offline manifest files and proposes nothing executable: it
> never deploys or rolls back anything, and never sends messages. Live reads
> (`snapshot`, `drift --live`) are GET-only through the shared client behind
> `--experimental`, using verified endpoints only; layouts, workflows and other
> kinds without a verified read API come from `--import-dir` exports. A
> readiness pass means only these narrow checks pass — verify against the real
> orgs before any promotion.
