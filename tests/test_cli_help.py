"""--help snapshot tests for the root and every module (TK-X-1)."""

from __future__ import annotations

import re

import pytest
from syrupy.assertion import SnapshotAssertion
from typer.testing import CliRunner

from zohokit.cli import app

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_BOX_MAP = str.maketrans({"╭": "┌", "╮": "┐", "╰": "└", "╯": "┘"})


def _normalize(text: str) -> str:
    """Strip ANSI colors and unify box-drawing across platforms.

    Rich renders rounded panels with color on Linux and square panels
    without color on Windows; the words, options and commands pinned by
    these snapshots are identical either way.
    """
    return _ANSI_RE.sub("", text).translate(_BOX_MAP)


MODULE_COMMANDS: list[list[str]] = [
    ["migration", "--help"],
    ["release", "--help"],
    ["workflow", "--help"],
    ["forms", "--help"],
    ["books", "--help"],
    ["metrics", "--help"],
    ["timeline", "--help"],
    ["lead-routing", "--help"],
]

runner = CliRunner()


def test_root_help_snapshot(snapshot: SnapshotAssertion) -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert _normalize(result.output) == snapshot


@pytest.mark.parametrize("argv", MODULE_COMMANDS)
def test_module_help_snapshot(argv: list[str], snapshot: SnapshotAssertion) -> None:
    result = runner.invoke(app, argv)
    assert result.exit_code == 0
    assert _normalize(result.output) == snapshot


def test_workflow_lint_metadata_help_keeps_brackets() -> None:
    """Rich markup must not swallow the ``[field api_names]`` help text."""
    result = runner.invoke(app, ["workflow", "lint", "--help"])
    assert result.exit_code == 0
    assert "JSON {module: [field api_names]}." in _normalize(result.output)
