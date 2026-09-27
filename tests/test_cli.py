"""CLI smoke tests (TK-X-1 scaffold) and module commands (TK-MIG-4)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from zohokit import __version__
from zohokit.cli import app
from zohokit.modules import MODULES

ROOT = Path(__file__).resolve().parent.parent
LEGACY = ROOT / "legacy"

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


def _fixture(name: str) -> str:
    return str(LEGACY / name / "examples.json")


def test_migration_audit_autodetects() -> None:
    result = runner.invoke(app, ["migration", "audit", _fixture("zoho-crm-migration-auditor")])
    assert result.exit_code == 0
    assert json.loads(result.output)["module"] == "migration"


def test_migration_audit_strict_exit_2() -> None:
    result = runner.invoke(
        app, ["migration", "audit", _fixture("zoho-crm-migration-auditor"), "--strict"]
    )
    assert result.exit_code == 2
    assert json.loads(result.output)["ready"] is False


def test_release_diff_table_and_explicit_format() -> None:
    result = runner.invoke(
        app,
        [
            "release",
            "diff",
            _fixture("zoho-release-readiness-audit"),
            "--format",
            "table",
            "--input-format",
            "legacy-v1",
        ],
    )
    assert result.exit_code == 0
    assert "removal_review" in result.output


def test_workflow_simulate_markdown() -> None:
    result = runner.invoke(
        app,
        ["workflow", "simulate", _fixture("zoho-workflow-rule-testbench"), "--format", "markdown"],
    )
    assert result.exit_code == 0
    assert result.output.startswith("# zohokit workflow report")


def test_forms_parity_strict_exit_2() -> None:
    result = runner.invoke(
        app, ["forms", "parity", _fixture("zoho-forms-parity-checker"), "--strict"]
    )
    assert result.exit_code == 2


def test_wrong_envelope_rejected() -> None:
    result = runner.invoke(app, ["migration", "audit", _fixture("zoho-release-readiness-audit")])
    assert result.exit_code == 1


def test_unknown_format_rejected() -> None:
    result = runner.invoke(app, ["migration", "audit", _fixture("zoho-crm-migration-auditor")])
    assert result.exit_code == 0
    result = runner.invoke(
        app,
        ["migration", "audit", _fixture("zoho-crm-migration-auditor"), "--input-format", "csv"],
    )
    assert result.exit_code == 1


def test_missing_file_exit_1() -> None:
    result = runner.invoke(app, ["migration", "audit", str(LEGACY / "nope.json")])
    assert result.exit_code == 1
