"""Architecture contract test: TK-ARCH-3 via import-linter."""

from __future__ import annotations

from importlinter import cli


def test_import_contracts() -> None:
    assert (
        cli.lint_imports(config_filename=".importlinter", no_cache=True, no_logo=True)
        == cli.EXIT_STATUS_SUCCESS
    )
