# SARIF 2.1.0 JSON schema (vendored, offline)

Source: https://json.schemastore.org/sarif-2.1.0.json
Upstream `$id`: https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json
Vendored: 2026-10-04. OASIS SARIF v2.1.0, draft-07.

`tests/unit/test_sarif_junit.py` validates every `render_sarif` payload
against `sarif-2.1.0.json` with `jsonschema`, so SARIF tests never touch
the network.
