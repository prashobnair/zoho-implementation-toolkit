# Release finding codes

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
