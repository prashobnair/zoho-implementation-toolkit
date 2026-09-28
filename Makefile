.PHONY: sync lint test schemas demo

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
