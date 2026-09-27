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
	@echo "JSON Schema export lands with the shared core (WP-07, TK-ARCH-5)."

demo:
	uv run zohokit version
	uv run zohokit modules list
