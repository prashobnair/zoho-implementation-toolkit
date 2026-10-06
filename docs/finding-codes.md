# Finding codes

Every finding carries a stable snake_case `code`, documented per module in
`src/zohokit/modules/<m>/codes.md` and aggregated here. Severity ranks
`error > review > warning > info`. A run is ready only when no error (and,
per module, no review) findings remain; `--strict` turns a not-ready run
into exit code 2.

## migration

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
| `fuzzy_duplicate_cluster` | review | In-source rows share an email, phone or fuzzy company name; one survivor suggested, never merged. |
| `would_duplicate_existing` | review | A source row matches an existing target record (fingerprint only). |
| `target_dedupe_coverage` | info | Target duplicate search coverage (`checked N / M`). |
| `stage_probability_mismatch` | warning | A row probability differs from the expected stage probability. |
| `inactive_owner` | error | An owner email belongs to an inactive target user. |
| `owner_unmapped` | error | An owner email matches no user in the target org. |
| `history_type_unsupported` | warning/info | A history type has no target module to hold it; info carries per-parent counts. |
| `reconcile_count_mismatch` | error | Source and target counts differ for the module. |
| `reconcile_field_diff` | review | A sampled target record differs from the transformed source. |
| `reconcile_relationship_gap` | error | A child row references a parent absent from the source. |

## release

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

## workflow

| Code | Severity | Meaning |
|---|---|---|
| `cycle_detected` | error | The trace revisited a state signature; simulation stopped. |
| `step_limit` | error | The rule trace exceeded the step budget. |
| `missing_owner` | error | An assign-owner action has no usable owner value. |
| `no_op_stage` | error | A set-stage action targets the stage already set. |
| `duplicate_followup` | error | The same follow-up would fire twice for one record. |
| `duplicate_side_effect` | error | A simulated email/webhook/task would fire twice for one record, action, template/url and day; the repeat was dropped. |
| `conflicting_field_updates` | error | Two rules on the same trigger update the same field to different values. |
| `potential_loop` | error | A rule writes fields that trigger other rules in a cycle; the chain path is reported. |
| `stale_field_reference` | error | A rule references a field absent from the module metadata. |
| `empty_rule` | warning | A rule has no actions. |
| `dead_rule` | warning | An inactive rule is still referenced (or never fires). |
| `webhook_failing` | error | A rule webhook has recent execution failures. |
| `near_limit` | warning | Per-module rule/action counts approach the configured limits. |
| `unsupported_construct` | review | A real-rule construct has no simulator representation; listed, never approximated. |
| `uncovered_rule` | info | No scenario case exercised the rule. |

## forms

Case issues are **info** when source and target handle them identically,
**error** when only one side has them. Only a source/target difference blocks.

| Code | Severity | Meaning |
|---|---|---|
| `required_missing` | info/error | A visible required field has no answer. |
| `invalid_choice` | info/error | A select answer is not one of the options. |
| `invalid_number` | info/error | A number/calculated field cannot be computed. |
| `invalid_calculation_sources` | info/error | A calculated field lacks exactly two known sources. |
| `invalid_visibility_reference` | info/error | `visible_if` references an unknown field or the field itself. |
| `visibility_cycle` | info/error | Fields reference each other in a `visible_if` cycle; treated as hidden. |
| `answer_for_hidden_field` | info | An answer for a hidden field was ignored. |
| `parity_mismatch` | error | A case's source and target outputs differ for a field; evidence carries both values. |

## books

| Code | Severity | Meaning |
|---|---|---|
| `duplicate_or_missing_deal_id` | error | A deal ID is empty or repeats. |
| `entity_currency_mismatch` | error | The deal entity is unknown or its currency differs. |
| `invalid_amount` | error | A malformed amount; that row's amount comparisons skipped. |
| `missing_invoice` | error | A deal has no invoice. |
| `duplicate_invoice_reference` | error | Several invoices reference one deal. |
| `cross_entity_invoice` | error | An invoice sits in the wrong legal entity. |
| `currency_mismatch` | error | Invoice currency differs from the deal currency. |
| `net_amount_mismatch` | error | Invoice net differs from the deal net. |
| `tax_not_reviewed` | error | The invoice tax was not reviewed. |
| `sync_failed` | error | The invoice sync state is failed. |
| `orphan_invoice_reference` | error | An invoice references no known deal. |

## metrics

| Code | Severity | Meaning |
|---|---|---|
| `future_snapshot` | error | A source timestamp is newer than `as_of`. |
| `stale_snapshot` | error | A source timestamp is older than the 24h freshness SLA. |
| `orphan_deal` | error | A deal references an unknown account. |
| `orphan_invoice` | error | An invoice references an unknown account. |
| `currency_mismatch` | error | An invoice is not in the report currency. |
| `duplicate_id` | error | A deal/invoice ID repeats; excluded from aggregates. |
| `invalid_staff_row` | error | A staff row breaks hours validation. |
| `invalid_utilization` | error | Aggregate utilization is impossible. |

## timeline

| Code | Severity | Meaning |
|---|---|---|
| `conflicting_claims` | error | Differing normalized values share a normalized claim key. |

## lead_routing

| Code | Severity | Meaning |
|---|---|---|
| `qualified_sales_inquiry` | info | Sales intent with confirmed budget and consent. |
| `consent_not_verified` | review | Consent is not granted; human queue. |
| `needs_human_triage` | review | Support/unknown intent; human queue. |
| `budget_unconfirmed` | review | Sales intent without confirmed budget; human queue. |
| `unrecognized_intent` | review | Intent is none of the known values; human queue. |
| `unsupported_channel` | review | Channel is not a known inbound channel; human queue. |
| `invalid_or_missing_e164` | review | No usable E.164 phone; human queue. |
| `phone_candidate_match` | review | E.164 matches an earlier lead; never merged. |
| `inferred_region` | info | Region came from the explicit `--default-region`. |
