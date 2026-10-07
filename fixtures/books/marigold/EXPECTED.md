# Marigold Labs month-end scenario (September 2026)

Offline fixture for the Books month-end workbench
(`fixtures/books/marigold/`): two legal entities (IN/INR, US/USD) plus
an unreachable EU entity, reconciled with `policy.yaml`,
`entity_map.yaml` and `fx_rates.csv`.

Run: `zohokit books reconcile recon.json --input-format legacy-v1
--policy policy.yaml --entity-map entity_map.yaml --fx-rates fx_rates.csv
--unavailable eu-entity`

Raw Books org IDs in the test profile only (`555000001/2/3`,
synthetic): `in-entity`, `us-entity`, `eu-entity`. Reports carry
`sha256:` fingerprints, never raw IDs (asserted in
`tests/unit/modules/test_books_recon.py`).

## Expected findings (exact set, asserted by `test_marigold_answer_key_exact_set`)

| Deal / row | Finding(s) | Why |
|---|---|---|
| d-in-01 | `within_tolerance` (info) | exact match |
| d-in-02 | `within_tolerance` (info) | 40/60 staged billing sums two invoices to the net (UC-BK-2) |
| d-in-03 | `outside_tolerance` | single invoice 500 below net, beyond abs 1.00 |
| d-in-04 | `under_invoiced` | staged pair sums 140000 vs 200000 |
| d-in-05 | `over_invoiced` | staged pair sums 120000 vs 100000 |
| d-in-06 | `missing_invoice` | no invoice |
| d-in-07 | `draft_invoice_excluded` (info) + `missing_invoice` | only a draft invoice, excluded by default |
| d-in-08 | `invalid_amount` + `missing_invoice` | malformed net `12.34.56`, row isolated (TK-FIX-2) |
| d-in-09 | `cross_entity_invoice` + `missing_invoice` | its invoice i-us-04 sits in the US org (misfiled key match, UC-BK-3) |
| d-in-10 | `fx_rate_missing` (review) | USD invoice on 2026-09-15, no rate for that date — never guessed |
| d-in-11 | `within_tolerance` (info) | USD 1000 × 88.4100 (2026-09-20) = INR 88410.00, converted shown |
| d-in-12 | `within_tolerance` (info) | 100000 − 5000 linked credit note = 95000 netted off |
| d-in-13 | — | closing 2026-08-31 US-Pacific: out of window |
| d-in-14 | — | closing 2026-10-01 IST: out of window |
| d-in-15 | `within_tolerance` (info) | closing 2026-09-30 IST: in window |
| d-us-01 | `within_tolerance` (info) | exact USD match |
| d-us-02 | `missing_invoice` | no invoice |
| d-eu-01 / i-eu-01 | — | org unreachable: `source_unavailable` on `eu-entity`, records skipped |
| i-us-02 | `cross_entity_invoice` | stray sharing the Marigold Labs name, flagged once on the invoice, never matched by name (UC-BK-3) |
| i-us-03 | `orphan_invoice_reference` | key matches no deal anywhere |
| cn-us-01 | `credit_note_unlinked` (review) | links to no known invoice |
