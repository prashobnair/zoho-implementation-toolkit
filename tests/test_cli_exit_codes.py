"""Exit-code contract tests: usage errors exit 1, never 2 (STD §3.5).

Exit 2 is reserved for blocked releases (``--strict`` with blocking
findings), so a CI gate can tell a typo from a blocked release. Every
framework usage error — unknown option, missing argument, bad value —
must exit 1. ``--strict`` behavior is unchanged (pinned elsewhere).
"""

from __future__ import annotations

from typer.testing import CliRunner

from zohokit.cli import app

runner = CliRunner()


def test_unknown_command_option_exits_1() -> None:
    result = runner.invoke(app, ["migration", "audit", "x.json", "--bogus"])
    assert result.exit_code == 1
    assert "No such option" in result.output


def test_unknown_root_option_exits_1() -> None:
    result = runner.invoke(app, ["--bogus"])
    assert result.exit_code == 1
    assert "No such option" in result.output


def test_missing_argument_exits_1() -> None:
    result = runner.invoke(app, ["migration", "audit"])
    assert result.exit_code == 1
    assert "Missing argument" in result.output


def test_bad_root_option_value_exits_1() -> None:
    result = runner.invoke(app, ["--max-api-calls", "abc", "version"])
    assert result.exit_code == 1
    assert "Invalid value" in result.output


def test_bad_command_option_value_exits_1() -> None:
    result = runner.invoke(app, ["migration", "audit", "x.json", "--max-api-calls", "abc"])
    assert result.exit_code == 1
    assert "Invalid value" in result.output
