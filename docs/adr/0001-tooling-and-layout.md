# ADR-0001: Tooling and layout

- Status: accepted
- Date: 2026-09-27

## Context

The toolkit merges 8 flat legacy repos into one package (`zohokit`) with a CLI.

## Decision

Python 3.11+, `uv` + `pyproject.toml` (PEP 621), `src/` layout, `uv.lock`
committed. Strict `ruff` + `mypy --strict` on `src/`. `pytest` + `hypothesis`.

## Consequences

CI matrix 3.11–3.13. Contributors install only `uv`.
