"""CLI exit-code parity: every legacy parity-golden input through the zohokit CLI.

For each manifest entry, run the matching ``zohokit <module> <command>``
with the manifest's extra args and assert the exit code equals the legacy
CLI's recorded exit code. This guards the --strict/ready contract per
STD §3.5 across all modules.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from zohokit.cli import app

ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_ROOT = ROOT / "tests" / "golden" / "legacy"

COMMANDS: dict[str, list[str]] = {
    "migration": ["migration", "audit"],
    "release": ["release", "diff"],
    "workflow": ["workflow", "simulate"],
    "forms": ["forms", "parity"],
    "books": ["books", "reconcile"],
    "metrics": ["metrics", "check"],
    "timeline": ["timeline", "compose"],
    "lead_routing": ["lead-routing", "route"],
}

runner = CliRunner()


def _cases() -> list[tuple[str, dict[str, Any]]]:
    cases: list[tuple[str, dict[str, Any]]] = []
    for module in sorted(COMMANDS):
        manifest_path = GOLDEN_ROOT / module / "_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest:
            cases.append((module, entry))
    return cases


@pytest.mark.parametrize(("module", "entry"), _cases())
def test_cli_exit_code_matches_legacy(module: str, entry: dict[str, Any]) -> None:
    """zohokit exit code equals the legacy CLI exit code for this input."""
    argv: list[str] = list(entry["argv"])
    assert argv[0] == "cli.py"
    command = [*COMMANDS[module], str(ROOT / argv[1]), *argv[2:]]
    result = runner.invoke(app, command)
    assert result.exit_code == entry["exit_code"], (
        f"{module} {entry['golden']}: zohokit exited {result.exit_code}, "
        f"legacy exited {entry['exit_code']}\n{result.output[:500]}"
    )
