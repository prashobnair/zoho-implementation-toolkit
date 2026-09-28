# Forms Parity (`forms`)

Prove a rebuilt form behaves like the original on every supplied case — field
by field, calculation by calculation.

## The problem

"We rebuilt our quote form by hand and the new estimate looks right on the
happy path. But does it match on every branch — delivery vs audit, missing vs
complete? One wrong operator quoted a customer the wrong price." — Marigold
Labs, forms migrator.

## What it does

- Evaluates source and target field lists over each answer case and compares
  outputs exactly (`parity_mismatch` carries both values as evidence).
- Evaluates visibility in dependency order: a field is visible only if its
  referenced field is visible and matches; answers to hidden fields are
  ignored and reported (`answer_for_hidden_field`).
- Detects `visible_if` cycles (`visibility_cycle`, fail closed as hidden) and
  bad references or calculation sources.
- Grades case issues fairly: identical handling on both sides is info; only a
  source/target difference blocks.

## Quickstart

```sh
uv run zohokit forms parity pair.json
uv run zohokit forms parity pair.json --strict
```

## How it works

The pure engine runs both offline form definitions over the offline answer
cases and emits findings with stable IDs; the run is ready only when every
case passes on both sides. Render with `--format json|table|markdown|html`
and write to a file with `--out`.

## Finding codes

| Code | Severity | Meaning |
|---|---|---|
| `required_missing` | info/error | A visible required field has no answer. Info when both sides agree, error on a difference. |
| `invalid_choice` | info/error | A select answer is not one of the options. |
| `invalid_number` | info/error | A number/calculated field cannot be computed. |
| `invalid_calculation_sources` | info/error | A calculated field lacks exactly two known sources. |
| `invalid_visibility_reference` | info/error | `visible_if` references an unknown field or the field itself. |
| `visibility_cycle` | info/error | Fields reference each other in a `visible_if` cycle; treated as hidden. |
| `answer_for_hidden_field` | info | An answer for a hidden field was ignored. |
| `parity_mismatch` | error | A case's source and target outputs differ for a field; evidence carries both values. |

## Scope & safety

> This module compares two offline form definitions over supplied cases: it
> never connects to Zoho, never submits a form, and only covers the cases you
> give it. A passing run proves equivalence on those cases — not that the
> source form itself is correct.
