"""CLI smoke tests (TK-X-1 scaffold)."""

from __future__ import annotations

from typer.testing import CliRunner

from zohokit import __version__
from zohokit.cli import app
from zohokit.modules import MODULES

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_modules_list_shows_all_eight() -> None:
    result = runner.invoke(app, ["modules", "list"])
    assert result.exit_code == 0
    for name in MODULES:
        assert name in result.output
    assert len(MODULES) == 8
