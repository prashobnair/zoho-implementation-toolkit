"""--help snapshot tests for the root and every module (TK-X-1)."""

from __future__ import annotations

import pytest
from syrupy.assertion import SnapshotAssertion
from typer.testing import CliRunner

from zohokit.cli import app

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
    assert result.output == snapshot


@pytest.mark.parametrize("argv", MODULE_COMMANDS)
def test_module_help_snapshot(argv: list[str], snapshot: SnapshotAssertion) -> None:
    result = runner.invoke(app, argv)
    assert result.exit_code == 0
    assert result.output == snapshot
