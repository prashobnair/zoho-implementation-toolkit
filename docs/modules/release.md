# Release Readiness (`release`)

Diff two configuration manifests and gate a promotion — removals, behavior
changes and missing dependencies, with a stable fingerprint.

## The problem

"Someone edited production directly again, and Friday's sandbox promotion has
dozens of changed components with no deploy order. If we remove the wrong
field, three layouts and a webhook break silently." — Marigold Labs, release
manager.

## What it does

- Diffs `before` vs `after` manifests by stable `(kind, name)` identity.
- Flags removed components (`removal_review`) and added/changed workflows,
  validations, functions or webhooks (`behavior_regression_review`).
- Lists dependencies missing from the target manifest (`missing_dependency`).
- Emits an order-free SHA-256 fingerprint, so reordered manifests compare equal.

## Quickstart

```sh
uv run zohokit release diff before-after.json
uv run zohokit release diff before-after.json --strict
```

## How it works

The pure engine compares two offline manifest lists and emits findings with
stable IDs plus a `ready_for_release` flag. Render with
`--format json|table|markdown|html|sarif|junit` and write to a file with `--out`.

## Finding codes

| Code | Severity | Meaning |
|---|---|---|
| `behavior_regression_review` | error | A workflow, validation, function or webhook was added or changed. |
| `removal_review` | error | A component was removed. |
| `missing_dependency` | error | A component depends on something absent from the target manifest. |

## Scope & safety

> This module diffs offline manifest files and proposes nothing executable: it
> never connects to Zoho, never deploys or rolls back anything, and never
> sends messages. A readiness pass means only these narrow checks pass —
> verify against the real orgs before any promotion.
