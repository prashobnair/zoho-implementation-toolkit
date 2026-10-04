# Marigold migration answer key (expected findings)

Seeded defects in the synthetic Pipedrive-shaped export and the finding
code that must catch each one. The CI test asserts every seeded defect
is detected with its expected code and that no unexpected
error-severity finding appears.

## Persons (800 rows; numbers are data rows, header excluded)

| # | Defect | Expected code |
|---|---|---|
| 1 | Row 11 has 2 cells (header needs 8) | `row_parse_error` (error) |
| 2 | Blank line after row 21 | `row_parse_error` (warning) |
| 3a | Rows 31+32 share an email | `unique_field_collision_in_batch` x2 |
| 3b | Survivor of the pair is row 31 | `fuzzy_duplicate_cluster` x1 |
| 4 | Row 41 email is not an address | `type_incompatible` (error) |
| 5 | Row 42 name is 81 chars (max 80) | `value_too_long` (error) |
| 6 | Row 43 phone cannot parse as E.164 | `type_incompatible` (error) |
| 7 | Rows 51+52 share external ID 9001 | `unique_field_collision_in_batch` x2 (error) |
| 8 | Row 61 owner is inactive | `inactive_owner` (error) |
| 9 | Row 62 owner matches no user | `owner_unmapped` (error) |
| 10 | Row 63 source maps to Pigeon (no such picklist value) | `picklist_value_missing` (error) |
| 11 | Row 71 email already exists in the target | `would_duplicate_existing` (review) |
| 12 | Row 72 name is empty (required) | `type_incompatible` (error) |
| 13a | Mapping targets Mystery__s (absent) | `unknown_target_field` x1 |
| 13b | Mapping writes id (read-only) | `read_only_target_field` x1 |
| 13c | Nickname column missing from header | `missing_source_column` x1 |

## Organizations (200 rows)

| # | Defect | Expected code |
|---|---|---|
| 14 | Rows 6+7 are fuzzy company duplicates | `fuzzy_duplicate_cluster` x1 (review) |
| 15 | Row 8 name is empty (required) | `type_incompatible` (error) |

## Deals (700 rows)

| # | Defect | Expected code |
|---|---|---|
| 16a | Row 101 stage Warp Drive is outside the picklist | `picklist_value_missing` x1 |
| 16b | Same row against the Deals pipeline | `unmapped_stage` x1 |
| 17 | Row 102 Qualification at 80% (expects 10%) | `stage_probability_mismatch` (warning) |
| 18 | Row 103 amount has 3 decimals | `type_incompatible` (error) |
| 19 | Row 104 currency XX is unknown | `type_incompatible` (error) |
| 20 | Row 105 close date cannot parse | `type_incompatible` (error) |
| 21 | Mandatory Pipeline has no mapping | `mandatory_field_unmapped` (error) |
| 22 | Account_Name lookup has no resolution | `lookup_unresolvable` (review) |

## Activities (300 rows)

| # | Defect | Expected code |
|---|---|---|
| 23 | Rows 12, 56, 151 are Fax (unsupported) | `history_type_unsupported` x3 + x1 info |

## Coverage

Live-search coverage per entity: `target_dedupe_coverage` (info x4).
