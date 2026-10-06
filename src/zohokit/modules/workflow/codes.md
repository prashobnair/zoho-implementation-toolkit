# Workflow finding codes

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
