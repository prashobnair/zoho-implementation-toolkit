# Differences from the original tools

`zohokit` re-implements the eight original `zoho-*` helpers offline, with the
same inputs, the same readiness flags and the same exit codes. On 37 captured
outputs the results are byte-equal to the original tools except for the
intentional fixes listed below. Each fix has a regression test.

## 0.1.0 in short (first release)

- One CLI, `zohokit`, over 8 ported Zoho helpers: migration audit, release
  diff, workflow simulation, forms parity, books reconciliation, metrics
  checks, timeline composition and lead routing — all offline, all byte-equal
  to the original tools on 37 captured outputs except documented fixes.
- One report envelope (JSON/table/Markdown/HTML) with stable finding IDs,
  a readiness flag and strict exit codes; every input/output model ships a
  versioned JSON Schema under `schemas/`.
- Docs site with a page per module and a full finding-code index; unavailable
  flags (`--live`, `--profile`, `--ai`, `--baseline`, `--max-api-calls`) fail
  loudly with the release that unlocks them. No live mode, no writes, no
  sends.
- Fixed during the port, each with a regression test: order-free release
  fingerprints; books row-level amount errors; metrics duplicate IDs and
  staff-hours validation; forms hidden-parent visibility and output-difference
  (`parity_mismatch`) findings; timeline claim normalization.

## Intentional differences

### Release fingerprint is order-free (`target_manifest_sha256`)

The release fingerprint sorts components by `(kind, name)` before hashing, so
list order can never change the hash. `target_manifest_sha256` is now
order-free, e.g. `01_examples.json` changed `0e1aabe6…` → `ca3d3e6e…`; all
other release goldens likewise.

### Metrics staff-hours validation (`invalid_staff_row`)

Staff rows are validated per row. A staff row with missing, non-numeric,
non-positive available hours, negative booked hours, or booked hours above
available hours records an `invalid_staff_row` error and is left out of the
utilization aggregate. `metrics/05_invalid_utilization.json` gains
`invalid_staff_row` for s-1 and drops `invalid_utilization` (valid rows now
aggregate to 50.00%).

### Metrics duplicate IDs (`duplicate_id`)

A repeated deal or invoice ID records a `duplicate_id` error and is excluded
from aggregates with an `excluded_rows` count, instead of being double
counted. All other books/metrics/timeline/lead-routing goldens are
byte-equal.

### Books row-level amount errors (`invalid_amount`)

A malformed deal or invoice amount records an `invalid_amount` error finding
on that row and skips its amount comparisons instead of aborting the whole
run. Amounts go through strict decimal-string parsing.

### Forms output differences (`parity_mismatch`)

Output differences now surface as `parity_mismatch` (error) findings, one per
differing case/field with both values as evidence. New invariant: a not-ready
report always carries an error/review finding. For example the
`delivery_calculation` case reports `estimate` `600` vs `203`.

### Forms agreed case issues stay info

Case issues identical on source and target are info (not blocking); only a
source/target difference blocks. Ready follows the legacy `all_pass` flag.
CLI exit codes match the legacy tools on all 37 golden inputs.

### Forms chained visibility (no golden change)

Visibility is evaluated in dependency order. A field is visible only if its
referenced field is visible and matches; answers to hidden fields are ignored
and reported as `answer_for_hidden_field` info. Fields in a `visible_if`
cycle get a `visibility_cycle` error and are treated as hidden. No forms
golden changed (chained visibility is absent from fixtures).

### Timeline claim normalization

Claim keys are normalized (casefold, strip, `-`/space → `_`); typed claims
(`date`, `number`, `money`, `text`) are normalized before comparison;
untyped claims keep exact string comparison. Conflicts surface as
`conflicting_claims` on the normalized key.

### Stable finding IDs

Finding identities are stable: discriminators come from identifying input
data (row IDs, field/case names, components), never positions. Forms surfaces
legacy case issues as findings, so every case issue is addressable by ID.

## Known issue KI-001

| ID | Modules | Issue | Impact | Planned fix |
|---|---|---|---|---|
| KI-001 | migration, lead_routing | Duplicate findings land on whichever record appears second (first-seen survivor selection is input-order dependent). Finding IDs themselves are stable for a fixed input order. | Baseline suppression and diff-reports key on stable IDs, so a reordered input can shift which record carries the duplicate finding. | migration v2 (planned) for duplicate clusters; lead-routing backtest (planned) |
