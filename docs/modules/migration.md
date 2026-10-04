# Migration Preflight (`migration`)

Audit a CRM migration source before import — know what will break while it is still cheap to fix.

## The problem

"We're moving 2,000 Pipedrive rows into Zoho CRM next quarter, and nobody can
tell us which contacts will duplicate, which deals will orphan, or which
stages won't map. We find out after go-live." — Marigold Labs, RevOps lead.

## What it does

- Validates every row has a usable source ID (`missing_id`, `duplicate_id`).
- Syntax-checks emails and flags duplicate candidates by normalized email
  (`invalid_email`, `possible_duplicate`) — candidates are reported, never merged.
- Checks foreign keys: people belong to known organizations, deals to known
  people, activities to known deals (`orphan_organization`, `orphan_person`,
  `orphan_deal`).
- Verifies every deal stage has an approved target mapping (`unmapped_stage`).

## Quickstart

```sh
uv run zohokit migration audit source.json
uv run zohokit migration audit source.json --strict
```

`--strict` exits 2 when the export is not ready for import; without it, a
not-ready run still exits 0 after printing the report.

## How it works

The pure engine reads one offline JSON envelope (organizations, people, deals,
activities plus the stage map) and emits findings with stable IDs plus a
`ready_for_import` flag. Render with `--format json|table|markdown|html|sarif|junit` and
write to a file with `--out`.

## Finding codes

| Code | Severity | Meaning |
|---|---|---|
| `missing_id` | error | A row has no source ID. |
| `duplicate_id` | error | A source ID repeats within its entity. |
| `invalid_email` | error | Email syntax cannot be matched safely. |
| `possible_duplicate` | review | Normalized email matches another source person. Never auto-merged. |
| `orphan_organization` | error | Person references an organization ID absent from the export. |
| `orphan_person` | error | Deal references a person ID absent from the export. |
| `unmapped_stage` | error | Deal stage has no approved target mapping. |
| `orphan_deal` | error | Activity references a deal ID absent from the export. |

## Scope & safety

> This module is offline and read-only: it audits a source file, never
> connects to Zoho, never imports or merges anything, and never sends
> messages. A readiness pass means only these narrow checks pass — pilot in a
> sandbox with mapped target IDs before any real cutover.
