# Forms finding codes

Case issues (`required_missing`, `invalid_choice`, `invalid_number`,
`invalid_calculation_sources`, `invalid_visibility_reference`,
`visibility_cycle`) are **info** when source and target handle them
identically, **error** when only one side has them. Only a source/target
difference blocks.

| Code | Severity | Meaning |
|---|---|---|
| `required_missing` | info/error | A visible required field has no answer. |
| `invalid_choice` | info/error | A select answer is not one of the options. |
| `invalid_number` | info/error | A number/calculated field cannot be computed. |
| `invalid_calculation_sources` | info/error | A calculated field lacks exactly two known sources. |
| `invalid_visibility_reference` | info/error | `visible_if` references an unknown field or the field itself. |
| `visibility_cycle` | info/error | Fields reference each other in a `visible_if` cycle; hidden (TK-FIX-5). |
| `answer_for_hidden_field` | info | An answer for a hidden field was ignored (TK-FIX-5). |
