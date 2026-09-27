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


def test_books_reconcile_and_strict() -> None:
    fixture = str(LEGACY / "zoho-books-sync-reconciler" / "examples.json")
    assert runner.invoke(app, ["books", "reconcile", fixture]).exit_code == 0
    strict = runner.invoke(app, ["books", "reconcile", fixture, "--strict"])
    assert strict.exit_code == 2
    assert json.loads(strict.output)["ready"] is False


def test_metrics_check_audiences() -> None:
    fixture = str(LEGACY / "zoho-analytics-metrics-contracts" / "examples.json")
    finance = runner.invoke(app, ["metrics", "check", fixture])
    assert finance.exit_code == 0
    sales = runner.invoke(app, ["metrics", "check", fixture, "--audience", "sales"])
    assert sales.exit_code == 0
    assert json.loads(finance.output)["run_id"] != json.loads(sales.output)["run_id"]
    bad = runner.invoke(app, ["metrics", "check", fixture, "--audience", "executive"])
    assert bad.exit_code == 1


def test_timeline_compose_client() -> None:
    fixture = str(LEGACY / "zoho-client-timeline-composer" / "examples.json")
    result = runner.invoke(app, ["timeline", "compose", fixture, "--audience", "client"])
    assert result.exit_code == 0
    assert "2026-02-15" not in result.output


def test_lead_routing_route_and_region() -> None:
    fixture = str(LEGACY / "zoho-lead-routing-lab" / "examples.json")
    result = runner.invoke(app, ["lead-routing", "route", fixture])
    assert result.exit_code == 0
    assert json.loads(result.output)["module"] == "lead_routing"
    regional = runner.invoke(app, ["lead-routing", "route", fixture, "--default-region", "IN"])
    assert regional.exit_code == 0
