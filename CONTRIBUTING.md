# Contributing

## Setup

```sh
uv sync
```

Requires Python 3.11+ (`requires-python = ">=3.11"`; CI matrix 3.11, 3.12, 3.13).

## Checks (must all pass)

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict src
uv run lint-imports
uv run pytest
```

Or `make lint test`.

## Branches and commits

- Branch name: `wp-<NN>-<short-slug>`.
- Conventional Commits with requirement IDs, e.g. `feat(core): add Finding model [TK-CORE-1]`.
- Every commit carries a trailer on its own line: `Agent: <name>`.
- Never push to `main`, never merge your own PR. The lead squash-merges after verification.

## Safety rules (non-negotiable)

- No writes to any Zoho org, ever (GET-only guard; plans only).
- Synthetic data only in fixtures, cassettes, logs and screenshots.
- No credentials in chat, code or commits. Live tests read GitHub secrets in CI only.
- AI features are opt-in, cited, evaluated and never auto-applied.
