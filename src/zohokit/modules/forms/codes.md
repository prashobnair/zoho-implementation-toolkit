# Forms finding codes

| Code | Severity | Meaning |
|---|---|---|
| `required_missing` | error | A visible required field has no answer. |
| `invalid_choice` | error | A select answer is not one of the options. |
| `invalid_number` | error | A number/calculated field cannot be computed. |
| `invalid_calculation_sources` | error | A calculated field lacks exactly two known sources. |
| `invalid_visibility_reference` | error | `visible_if` references an unknown field or the field itself. |
| `visibility_cycle` | error | Fields reference each other in a `visible_if` cycle; hidden (TK-FIX-5). |
| `answer_for_hidden_field` | info | An answer for a hidden field was ignored (TK-FIX-5). |
