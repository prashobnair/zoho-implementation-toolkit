# Marigold migration answer key (expected findings)

Seeded defects in the synthetic Pipedrive-shaped export and the finding
code that must catch each one. Numbers are 1-based physical file lines
(the header is line 1): every per-record finding carries its line in
evidence and keys on the stable source record ID (never a position).
Only `row_parse_error` is positional (a parse fault has no record to
key on). The CI test asserts exact set equality between the detected
(entity, code, source_id, line, severity) tuples and `answer_key.json`,
with zero unexpected error-severity findings.

## Persons (800 data rows + 1 blank line)

| # | Defect | Expected code |
|---|---|---|
| 1 | Line 12 has 2 cells (header needs 8) | `row_parse_error` (error) |
| 2 | Line 23 is blank | `row_parse_error` (warning) |
| 3a | Lines 33+34 (IDs 31+32) share an email | `unique_field_collision_in_batch` x2 |
| 3b | Survivor of the pair is ID 31 | `fuzzy_duplicate_cluster` x1 |
| 4 | Line 43 (ID 41) email is not an address | `type_incompatible` (error) |
| 5 | Line 44 (ID 42) name is 81 chars (max 80) | `value_too_long` (error) |
| 6 | Line 45 (ID 43) phone cannot parse as E.164 | `type_incompatible` (error) |
| 7 | Lines 53+54 share external ID 9001 | `unique_field_collision_in_batch` x2 (error) |
| 8 | Line 63 (ID 61) owner is inactive | `inactive_owner` (error) |
| 9 | Line 64 (ID 62) owner matches no user | `owner_unmapped` (error) |
| 10 | Line 65 (ID 63) Pigeon is no picklist value | `picklist_value_missing` (error) |
| 11 | Line 73 (ID 71) email already exists in the target | `would_duplicate_existing` (review) |
| 12 | Line 74 (ID 72) name is empty (required) | `type_incompatible` (error) |
| 13a | Mapping targets Mystery (absent) | `unknown_target_field` x1 |
| 13b | Mapping writes id (read-only) | `read_only_target_field` x1 |
| 13c | Nickname column missing from header | `missing_source_column` x1 |

## Organizations (200 rows)

| # | Defect | Expected code |
|---|---|---|
| 14 | Lines 7+8 (IDs 501+502) are fuzzy duplicates | `fuzzy_duplicate_cluster` x1 (review) |
| 15 | Line 9 (ID 503) name is empty (required) | `type_incompatible` (error) |

## Deals (700 rows)

| # | Defect | Expected code |
|---|---|---|
| 16a | Line 102 (ID 101) stage Warp Drive is outside the picklist | `picklist_value_missing` x1 |
| 16b | Same row against the Deals pipeline | `unmapped_stage` x1 |
| 17 | Line 103 (ID 102) Qualification 80%, expects 10% | `stage_probability_mismatch` (warning) |
| 18 | Line 104 (ID 103) amount has 3 decimals | `type_incompatible` (error) |
| 19 | Line 105 (ID 104) currency XX is unknown | `type_incompatible` (error) |
| 20 | Line 106 (ID 105) close date cannot parse | `type_incompatible` (error) |
| 21 | Mandatory Pipeline has no mapping | `mandatory_field_unmapped` (error) |
| 22 | Account_Name lookup has no resolution | `lookup_unresolvable` (review) |

## Activities (300 rows)

| # | Defect | Expected code |
|---|---|---|
| 23 | Lines 13, 57, 152 (IDs 12, 56, 151) are Fax | `history_type_unsupported` x3 + x1 info |

## Coverage

Live-search coverage per entity: `target_dedupe_coverage` (info x4).
