# Recorded Zoho responses live here (redacted, synthetic-safe).

Cassettes are recorded redacted (the shared redactor runs before write)
and deterministically slimmed to stay committable:

- `settings/fields` responses keep at most 25 fields per module, sorted
  by `api_name` and always including the module's mandatory/system
  fields (`id`, `Owner`, `Created_Time`, `Last_Name`/`Deal_Name`, plus
  any field with `system_mandatory: true`). Each kept field holds only
  `api_name`, `field_label`, `data_type`, `length`, `read_only`,
  `system_mandatory`, `json_type`, `lookup.module.api_name`, and
  `pick_list_values[].actual_value` (first 10 by value).
- `settings/modules` responses keep only `api_name`, `module_name`,
  `singular_label`, `plural_label`, `api_supported`, `editable`,
  `viewable`, `generated_type`, `id` per module.

Timestamps (ISO-8601) and Zoho record IDs survive intact; only the org
ID is pseudonymised (`org-<first 8 hex of sha256>`, stable across
files), while user identity keys (`zuid`/`zgid`), contact details and
`state`/`city` in user/org contexts stay masked. Pagination tokens are
replaced whole with `[redacted-token]`.
