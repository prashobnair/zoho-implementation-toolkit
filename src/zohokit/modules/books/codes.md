# Books finding codes

| Code | Severity | Meaning |
|---|---|---|
| `duplicate_or_missing_deal_id` | error | A deal ID is empty or repeats. |
| `entity_currency_mismatch` | error | The deal entity is unknown or its currency differs. |
| `invalid_amount` | error | A malformed amount; that row's amount comparisons skipped (TK-FIX-2). |
| `missing_invoice` | error | A deal has no invoice. |
| `duplicate_invoice_reference` | error | Several invoices reference one deal. |
| `cross_entity_invoice` | error | An invoice sits in the wrong legal entity. |
| `currency_mismatch` | error | Invoice currency differs from the deal currency. |
| `net_amount_mismatch` | error | Invoice net differs from the deal net. |
| `tax_not_reviewed` | error | The invoice tax was not reviewed. |
| `sync_failed` | error | The invoice sync state is failed. |
| `orphan_invoice_reference` | error | An invoice references no known deal. |
