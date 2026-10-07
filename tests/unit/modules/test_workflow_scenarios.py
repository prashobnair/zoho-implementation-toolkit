"""Scenario runner + coverage (UC-WF-2, TK-WF-F5/F6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from zohokit.modules.workflow.scenario import (
    coverage_block,
    run_directory,
    run_suite,
    suite_findings,
)

ROOT = Path(__file__).resolve().parent.parent.parent.parent
MARIGOLD = ROOT / "scenarios" / "marigold-labs" / "rules"


def test_marigold_suite_passes_with_full_coverage() -> None:
    """Marigold rule suite: green with >= 90% rule coverage (acceptance)."""
    suites = run_directory(MARIGOLD)
    assert len(suites) == 1
    suite = suites[0]
    assert suite.passed
    assert suite.rule_coverage >= 0.90
    assert suite.rule_coverage == 1.0
    assert suite.branch_coverage == 1.0
    assert suite.uncovered_rules == ()
    assert len(suite.cases) == 10
    assert "scenario_case_failed" not in [finding.code for finding in suite_findings(suite)]


def test_marigold_report_carries_no_uncovered_rule() -> None:
    suite = run_directory(MARIGOLD)[0]
    assert [finding.code for finding in suite_findings(suite)] == []


def test_case_mismatch_is_an_error_finding(tmp_path: Path) -> None:
    target = tmp_path / "bad.yaml"
    target.write_text(
        "version: 1\nrules:\n"
        "  - id: r-never\n"
        "    event: {type: record_created}\n"
        "    actions:\n"
        "      - {type: assign_owner, owner: x}\n"
        "cases:\n"
        "  - name: wrong-expectation\n"
        "    given:\n"
        "      record: {id: z}\n"
        "      event: record_created\n"
        "    then:\n"
        "      fired: [r-other]\n",
        encoding="utf-8",
    )
    suite = run_suite(target)
    assert not suite.passed
    findings = suite_findings(suite)
    codes = sorted(finding.code for finding in findings)
    assert "scenario_case_failed" in codes
    assert "uncovered_rule" not in codes
    assert suite.rule_coverage == 1.0


def test_unfired_rule_is_info_only(tmp_path: Path) -> None:
    target = tmp_path / "partial.yaml"
    target.write_text(
        "version: 1\nrules:\n"
        "  - id: r-fired\n"
        "    event: {type: record_created}\n"
        "    actions:\n"
        "      - {type: assign_owner, owner: x}\n"
        "  - id: r-quiet\n"
        "    event: {type: record_edited}\n"
        "    criteria: {field: Amount, op: gt, value: 999}\n"
        "    actions:\n"
        "      - {type: assign_owner, owner: y}\n"
        "cases:\n"
        "  - name: only-create\n"
        "    given:\n"
        "      record: {id: z}\n"
        "      event: record_created\n"
        "    then:\n"
        "      fired: [r-fired]\n"
        "      no_findings: true\n",
        encoding="utf-8",
    )
    suite = run_suite(target)
    assert suite.passed
    assert suite.rule_coverage == 0.5
    findings = suite_findings(suite)
    assert [finding.code for finding in findings] == ["uncovered_rule"]
    assert findings[0].entity_id == "r-quiet"
    assert str(findings[0].severity) == "info"


def test_params_expand_cases() -> None:
    suite = run_suite(MARIGOLD / "deal_lifecycle.yaml")
    names = [case.name for case in suite.cases]
    assert "create-nonpositive[zero]" in names
    assert "create-nonpositive[negative]" in names


def test_missing_directory_is_input_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing"):
        run_directory(tmp_path / "nope")


def test_empty_directory_is_input_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no scenario files"):
        run_directory(tmp_path)


def test_coverage_block_carries_numbers_per_suite() -> None:
    """The JSON report coverage block: rules/branches covered/total + suites."""
    suites = run_directory(MARIGOLD)
    block = coverage_block(suites)
    assert block["rules"] == {"covered": 5, "total": 5}
    assert block["branches"] == {"covered": 5, "total": 5}
    assert len(block["suites"]) == 1
    entry = block["suites"][0]
    assert entry["file"] == "deal_lifecycle.yaml"
    assert len(entry["cases"]) == 10
    assert all(case["passed"] for case in entry["cases"])
    assert entry["rules"] == {
        "covered": [
            "ml-assign-owner",
            "ml-close-notify",
            "ml-high-value",
            "ml-negotiation-task",
            "ml-qualify",
        ],
        "uncovered": [],
        "total": 5,
    }
    assert entry["branches"] == {
        "covered": [
            "ml-assign-owner",
            "ml-close-notify",
            "ml-high-value",
            "ml-negotiation-task",
            "ml-qualify",
        ],
        "total": 5,
    }


def test_mismatch_details_carry_expected_and_actual(tmp_path: Path) -> None:
    """JUnit details name the field with expected/actual values."""
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
    suite = run_suite(target)
    assert not suite.passed
    assert suite.cases[0].failures == ("state field Owner differs",)
    assert suite.cases[0].details == ("state field Owner: expected 'somebody-else', got 'x'",)
    findings = suite_findings(suite)
    assert [finding.code for finding in findings] == ["scenario_case_failed"]
    assert findings[0].evidence == {"failures": ["state field Owner differs"]}
