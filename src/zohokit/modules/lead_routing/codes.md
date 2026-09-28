# Lead routing finding codes

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
