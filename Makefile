.PHONY: sync lint test schemas demo record scrub cassette-scan

sync:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy --strict src
	uv run lint-imports

test:
	uv run pytest

schemas:
	uv run python scripts/export_schemas.py

demo:
	uv run zohokit version
	uv run zohokit modules list

# Record one redacted cassette through the GET-only client (TK-CONN-9).
# Refuses to run in CI. Example: make record MODULE=crm PROFILE=dev-in ENDPOINT=/crm/v8/org
record:
	uv run python scripts/record_cassette.py --module "$(MODULE)" --profile "$(PROFILE)" --path "$(ENDPOINT)" --out "cassettes/$(MODULE)/$(notdir $(ENDPOINT)).json"

# Re-run the shared redactor over every recorded cassette (STD-X2).
scrub:
	uv run python scripts/scrub_cassettes.py

cassette-scan:
	uv run python scripts/cassette_scan.py
