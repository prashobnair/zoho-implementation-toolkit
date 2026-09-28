# Schemas

Every input and output model exports JSON Schema to `schemas/<module>/<name>.v<N>.json`:
`input.v1.json` is the module's offline input envelope, `report.v1.json` is the
shared report envelope (one copy per module so each output resolves locally).

Regenerate with `make schemas` (`uv run python scripts/export_schemas.py`) after
any model change and commit the result. CI fails when the export is stale
(`make schemas && git diff --exit-code`). Bump `v<N>` only for breaking
contract changes.
