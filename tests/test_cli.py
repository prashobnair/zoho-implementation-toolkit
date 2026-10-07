"""CLI smoke tests (TK-X-1 scaffold) and module commands (TK-MIG-4)."""

from __future__ import annotations

import json
from pathlib import Path

from syrupy.assertion import SnapshotAssertion
from typer.testing import CliRunner

from zohokit import __version__
from zohokit.cli import app
from zohokit.modules import MODULES

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_INPUTS = ROOT / "tests" / "golden" / "legacy"

_FIXTURES = {
    "zoho-crm-migration-auditor": GOLDEN_INPUTS / "migration" / "inputs" / "examples.json",
    "zoho-release-readiness-audit": GOLDEN_INPUTS / "release" / "inputs" / "examples.json",
    "zoho-workflow-rule-testbench": GOLDEN_INPUTS / "workflow" / "inputs" / "examples.json",
    "zoho-forms-parity-checker": GOLDEN_INPUTS / "forms" / "inputs" / "examples.json",
    "zoho-books-sync-reconciler": GOLDEN_INPUTS / "books" / "inputs" / "examples.json",
    "zoho-analytics-metrics-contracts": GOLDEN_INPUTS / "metrics" / "inputs" / "examples.json",
    "zoho-client-timeline-composer": GOLDEN_INPUTS / "timeline" / "inputs" / "examples.json",
    "zoho-lead-routing-lab": GOLDEN_INPUTS / "lead_routing" / "inputs" / "examples.json",
}

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
    return str(_FIXTURES[name])


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


def test_workflow_simulate_v2_trace_snapshot(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    """A v2 rule set simulates through the CLI with a snapshot trace (TK-WF-F2)."""
    fixture = tmp_path / "rules.json"
    fixture.write_text(
        json.dumps(
            {
                "rules": [
                    {
                        "id": "promote",
                        "event": {"type": "record_created"},
                        "priority": 1,
                        "actions": [
                            {"type": "field_update", "field": "Stage", "value": "Negotiation"}
                        ],
                    },
                    {
                        "id": "followup",
                        "event": {"type": "stage_changed", "field": "Stage"},
                        "priority": 2,
                        "criteria": {"field": "Stage", "op": "changed_to", "value": "Negotiation"},
                        "actions": [{"type": "create_task", "value": "Follow up", "delay_days": 2}],
                    },
                ],
                "record": {"id": "d-2", "Stage": "Proposal"},
            }
        ),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["workflow", "simulate", str(fixture)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert set(payload["simulation"]) == {"trace", "ledger", "external_actions", "days_elapsed"}
    assert payload["simulation"]["external_actions"] == 0
    assert payload["simulation"] == snapshot


MARIGOLD_RULES = str(ROOT / "scenarios" / "marigold-labs" / "rules")


def test_workflow_test_json_carries_coverage(tmp_path: Path) -> None:
    """The scenario JSON report carries the coverage block (TK-WF-F6)."""
    out = tmp_path / "report.json"
    result = runner.invoke(app, ["workflow", "test", MARIGOLD_RULES, "--out", str(out)])
    assert result.exit_code == 0, result.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["coverage"]["rules"] == {"covered": 5, "total": 5}
    assert payload["coverage"]["branches"] == {"covered": 5, "total": 5}
    suites = payload["coverage"]["suites"]
    assert [entry["file"] for entry in suites] == ["deal_lifecycle.yaml"]
    assert len(suites[0]["cases"]) == 10


def test_workflow_test_junit_lists_every_case(tmp_path: Path) -> None:
    """JUnit carries one testcase per scenario case, passing included."""
    import xml.etree.ElementTree as xml

    out = tmp_path / "cases.xml"
    result = runner.invoke(
        app, ["workflow", "test", MARIGOLD_RULES, "--format", "junit", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    suite = xml.parse(str(out)).getroot()
    assert suite.tag == "testsuite"
    assert suite.attrib["tests"] == "10"
    assert suite.attrib["failures"] == "0"
    cases = suite.findall("testcase")
    assert len(cases) == 10
    assert {case.attrib["classname"] for case in cases} == {"deal_lifecycle"}
    names = [case.attrib["name"] for case in cases]
    assert "create-nonpositive[zero]" in names
    assert "create-nonpositive[negative]" in names
    assert all(case.find("failure") is None for case in cases)


def test_workflow_test_junit_failure_names_field_expected_actual(tmp_path: Path) -> None:
    """A failing case carries the mismatch detail (field, expected, actual)."""
    import xml.etree.ElementTree as xml

    target = tmp_path / "state.yaml"
    target.write_text(
        "version: 1\nrules:\n"
        "  - id: r-state\n"
        "    event: {type: record_created}\n"
        "    actions:\n"
        "      - {type: assign_owner, owner: x}\n"
        "cases:\n"
        "  - name: wrong-owner\n"
        "    given:\n"
        "      record: {id: z}\n"
        "      event: record_created\n"
        "    then:\n"
        "      state: {Owner: somebody-else}\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "workflow",
            "test",
            str(tmp_path),
            "--format",
            "junit",
            "--out",
            str(tmp_path / "cases.xml"),
        ],
    )
    assert result.exit_code == 0, result.output
    suite = xml.parse(str(tmp_path / "cases.xml")).getroot()
    assert suite.attrib["tests"] == "1"
    assert suite.attrib["failures"] == "1"
    failure = suite.find("testcase/failure")
    assert failure is not None
    assert "Owner" in failure.attrib["message"]
    assert "somebody-else" in failure.attrib["message"]
    assert "'x'" in failure.attrib["message"]
    strict = runner.invoke(app, ["workflow", "test", str(tmp_path), "--strict"])
    assert strict.exit_code == 2


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
    result = runner.invoke(app, ["migration", "audit", str(GOLDEN_INPUTS / "nope.json")])
    assert result.exit_code == 1


def test_books_reconcile_and_strict() -> None:
    fixture = _fixture("zoho-books-sync-reconciler")
    assert runner.invoke(app, ["books", "reconcile", fixture]).exit_code == 0
    strict = runner.invoke(app, ["books", "reconcile", fixture, "--strict"])
    assert strict.exit_code == 2
    assert json.loads(strict.output)["ready"] is False


def test_metrics_check_audiences() -> None:
    fixture = _fixture("zoho-analytics-metrics-contracts")
    finance = runner.invoke(app, ["metrics", "check", fixture])
    assert finance.exit_code == 0
    sales = runner.invoke(app, ["metrics", "check", fixture, "--audience", "sales"])
    assert sales.exit_code == 0
    assert json.loads(finance.output)["run_id"] != json.loads(sales.output)["run_id"]
    bad = runner.invoke(app, ["metrics", "check", fixture, "--audience", "executive"])
    assert bad.exit_code == 1


def test_timeline_compose_client() -> None:
    fixture = _fixture("zoho-client-timeline-composer")
    result = runner.invoke(app, ["timeline", "compose", fixture, "--audience", "client"])
    assert result.exit_code == 0
    assert "2026-02-15" not in result.output


def test_lead_routing_route_and_region() -> None:
    fixture = _fixture("zoho-lead-routing-lab")
    result = runner.invoke(app, ["lead-routing", "route", fixture])
    assert result.exit_code == 0
    assert json.loads(result.output)["module"] == "lead_routing"
    regional = runner.invoke(app, ["lead-routing", "route", fixture, "--default-region", "IN"])
    assert regional.exit_code == 0
