# Threat model (short STRIDE table)

| Threat | Applies to | Mitigation |
|---|---|---|
| Spoofing (fake Zoho responses) | Connector cassettes, live reads | Pydantic validation of every response; `contract_drift` on missing fields (STD-H3) |
| Tampering (edited fixtures) | Offline audits | Canonical-hash run provenance; golden outputs in CI |
| Repudiation (who approved what) | Baselines, resolutions | Approver + expiry recorded in baseline/suppression files |
| Information disclosure (PII leak) | Logs, cassettes, reports, prompts | Shared redactor (STD-X1/X2); redaction scan in CI |
| Denial of service (API overuse) | Live reads | Call budget `--max-api-calls`, backoff + `Retry-After` (STD-L5/H1) |
| Elevation (write to Zoho) | All commands | GET-only transport guard raising `SafetyGuardError` (exit 4); plans only (STD-W1) |
