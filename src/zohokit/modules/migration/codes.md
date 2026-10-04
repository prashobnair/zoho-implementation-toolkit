# Migration finding codes

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
| `row_parse_error` | error/warning | A source row cannot be parsed; it is excluded from checks. |
| `unknown_target_field` | error | A mapped target field is absent from the target metadata. |
| `read_only_target_field` | error | A mapped target field is read-only in the target. |
| `missing_source_column` | error | A mapped source column is absent from the export header. |
| `type_incompatible` | error | A value cannot be converted for the target field type. |
| `value_too_long` | error | A value exceeds the target field length (max in evidence). |
| `picklist_value_missing` | error | A value is not an allowed target picklist value. |
| `mandatory_field_unmapped` | error | A mandatory target field has no mapping. |
| `lookup_unresolvable` | review | A lookup field has no entity resolution in the mapping. |
| `unique_field_collision_in_batch` | error | Two batch rows share one unique target value. |
