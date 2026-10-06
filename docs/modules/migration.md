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
- Preflight for real exports: a `mapping.yaml` DSL (source column → Zoho
  `api_name` plus transforms) checked against the target org's actual
  field metadata, with Pipedrive, HubSpot and generic CSV readers.

## Quickstart

```sh
uv run zohokit migration audit source.json
uv run zohokit migration audit source.json --strict
```

```sh
uv run zohokit migration preflight --mapping mapping.yaml --source pipedrive/ --fields-dir fields/
```

`--strict` exits 2 when the export is not ready for import; without it, a
not-ready run still exits 0 after printing the report. The preflight
reads `<source_kind>.csv` per mapped entity from `--source`, and target
metadata (`fields_<Module>.json`) from `--fields-dir` — or live from the
org with `--live --profile NAME` (verified fields endpoint, read-only).

## How it works

The pure engine reads one offline JSON envelope (organizations, people, deals,
activities plus the stage map) and emits findings with stable IDs plus a
`ready_for_import` flag. Render with `--format json|table|markdown|html|sarif|junit|xlsx` and
write to a file with `--out` (`xlsx` needs `--out`: workbooks cannot print
to stdout).

### Mapping DSL

Each entity maps source columns onto target fields with ordered
transforms (`trim`, `casefold`, `e164(region=IN)`, `date(format=...)`,
`money(currency_col=...)` via the shared money parser, `map(values=...)`,
`concat(fields=[...])`). An invalid transform is a config error naming
its file line. Source readers detect encoding and delimiters, tolerate
BOM/CRLF/quoted newlines, and stream rows; a bad row becomes a
`row_parse_error` finding, never an aborted run. Every mapped field is
checked against the target metadata: unknown or read-only targets,
missing source columns, type mismatches, over-length values (with the
max), missing picklist values, unmapped mandatory fields, unresolvable
lookups, and unique collisions in the batch (fingerprinted, never raw).
Duplicate clusters (normalized email, E.164 phone, fuzzy company name at
token-set ratio 85+) report one suggested survivor per cluster and are
never merged; survivor choice and finding placement are deterministic
under input reordering. Deal stages validate against the target Stage
picklist (with optional expected probabilities per stage); owner emails
resolve against target users (inactive or unmapped owners are errors,
emails redacted); history types outside the declared supported list warn.
Live target duplicate search (`--live --profile NAME --experimental`,
budget-aware with `checked N / M` coverage) fingerprints matches only.

## Finding codes

| Code | Severity | Meaning |
|---|---|---|
| `missing_id` | error | A row has no source ID. |
| `duplicate_id` | error | A source ID repeats within its entity. |
| `invalid_email` | error | Email syntax cannot be matched safely. |
| `possible_duplicate` | review | Normalized email matches another source person. Never auto-merged. |
| `orphan_organization` | error | Person references an organization ID absent from the export. |
| `orphan_person` | error | Deal references a person ID absent from the export. |
| `unmapped_stage` | error | Deal stage has no approved target mapping (legacy envelope) or no entry in the target Stage picklist (preflight). |
| `orphan_deal` | error | Activity references a deal ID absent from the export. |
| `row_parse_error` | error/warning | A source row cannot be parsed; it is excluded from checks. |
| `unknown_target_field` | error | A mapped target field is absent from the target metadata. |
| `read_only_target_field` | error | A mapped target field is read-only in the target. |
| `missing_source_column` | error | A mapped source column is absent from the export header. |
| `type_incompatible` | error | A value cannot be converted for the target field type, or a required value is missing. |
| `value_too_long` | error | A value exceeds the target field length (max in evidence). |
| `picklist_value_missing` | error | A value is not an allowed target picklist value. |
| `mandatory_field_unmapped` | error | A mandatory target field has no mapping. |
| `lookup_unresolvable` | review | A lookup field has no entity resolution in the mapping. |
| `unique_field_collision_in_batch` | error | Two batch rows share one unique target value. |
| `fuzzy_duplicate_cluster` | review | Rows share an email, phone or fuzzy company name; one survivor suggested, never merged. |
| `would_duplicate_existing` | review | A source row matches an existing target record (fingerprint only). |
| `target_dedupe_coverage` | info | Target duplicate search coverage (`checked N / M`). |
| `unmapped_stage` | error | Deal stage has no approved target mapping (legacy envelope) or no entry in the target Stage picklist (preflight). |
| `stage_probability_mismatch` | warning | A row probability differs from the expected stage probability. |
| `inactive_owner` | error | An owner email belongs to an inactive target user. |
| `owner_unmapped` | error | An owner email matches no user in the target org. |
| `history_type_unsupported` | warning/info | A history type has no target module to hold it; info carries per-parent counts. |
| `reconcile_count_mismatch` | error | Source and target counts differ for the module. |
| `reconcile_field_diff` | review | A sampled target record differs from the transformed source. |
| `reconcile_relationship_gap` | error | A child row references a parent absent from the source. |

## Import plan and reconciliation

`migration plan --mapping mapping.yaml --source pipedrive/ --out plan/`
writes the signed import plan: batches in dependency order (Accounts →
Contacts → Deals → Activities/Notes) with idempotency keys
(`source_system:source_id`), estimated API calls, the recommended
External ID field, and a rollback note explaining why rollback needs a
target-ID ledger captured at import time.

`migration reconcile --mapping mapping.yaml --source pipedrive/
--target dumps/ --workbook reconcile.xlsx` compares the export against
target dumps (`<TargetModule>.csv`): count parity, a seeded sample of
field-level compares with transforms applied, relationship integrity and
stage distribution deltas. The workbook carries Summary / Counts /
Sample diffs / Relationships tabs; the Marigold worked example
(`fixtures/migration/marigold/`, generated by
`scripts/gen_marigold_migration.py`) documents every seeded defect and
its finding code in `EXPECTED.md`.

## Scope & safety

> This module is offline and read-only: it audits a source file, never
> connects to Zoho, never imports or merges anything, and never sends
> messages. A readiness pass means only these narrow checks pass — pilot in a
> sandbox with mapped target IDs before any real cutover.
