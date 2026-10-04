"""SARIF 2.1.0 and JUnit XML renderer tests (TK-CORE-8).

SARIF payloads validate against the official schema vendored offline at
``tests/sarif-schema/sarif-2.1.0.json`` (OASIS SARIF v2.1.0); JUnit
payloads parse with ``junitparser``. No network is used by either test.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
from junitparser import JUnitXml
from typer.testing import CliRunner

from zohokit.cli import app
from zohokit.core.baseline import Baseline, BaselineEntry, apply_baseline
from zohokit.core.findings import Finding, Report, Severity
from zohokit.reports import render_junit, render_sarif

ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((ROOT / "tests" / "sarif-schema" / "sarif-2.1.0.json").read_text())
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
runner = CliRunner()


def _finding(
    code: str,
    entity_id: str,
    severity: Severity = Severity.ERROR,
    evidence: dict[str, object] | None = None,
) -> Finding:
    return Finding.create(
        module="release",
        code=code,
        severity=severity,
        entity="manifest",
        entity_id=entity_id,
        message=f"{code}: {entity_id}",
        evidence={key: str(value) for key, value in (evidence or {}).items()},
        remediation="Review the change before promoting.",
        docs_url="https://example.invalid/codes",
        discriminator=entity_id,
    )


def sample_report() -> Report:
    findings = [
        _finding("removal_review", "field:Deals.External_Ref"),
        _finding("field_type_change", "field:Deals.Amount", Severity.REVIEW),
        _finding("layout_only", "layout:Deals.Main", Severity.INFO),
    ]
    return Report.build(
        module="release",
        run_id="run-0001",
        started_at=NOW,
        finished_at=NOW,
        findings=findings,
        ready=False,
    )


def test_sarif_validates_against_official_schema() -> None:
    log = json.loads(render_sarif(sample_report()))
    jsonschema.validate(log, SCHEMA)
    assert log["version"] == "2.1.0"
    assert log["runs"][0]["tool"]["driver"]["name"] == "zohokit"


def test_sarif_has_one_result_per_finding_with_location() -> None:
    report = sample_report()
    log = json.loads(render_sarif(report))
    results = log["runs"][0]["results"]
    assert len(results) == len(report.findings) == 3
    assert [item["ruleId"] for item in results] == [
        "zohokit/removal_review",
        "zohokit/field_type_change",
        "zohokit/layout_only",
    ]
    assert [item["level"] for item in results] == ["error", "warning", "note"]
    first_location = results[0]["locations"][0]
    assert first_location["physicalLocation"]["artifactLocation"]["uri"] == "release.json"
    assert first_location["properties"]["jsonPointer"] == "/findings/0"
    assert results[0]["partialFingerprints"]["zohokit-finding-id/v1"] == report.findings[0].id


def test_sarif_uses_evidence_file_and_marks_suppressed() -> None:
    error = _finding("removal_review", "field:X", evidence={"file": "config/zoho/field.json"})
    baseline = Baseline(
        suppressions=[
            BaselineEntry(id=error.id, reason="Accepted.", approver="sam", expires=NOW.date())
        ]
    )
    report = apply_baseline(
        Report.build(
            module="release",
            run_id="run-0001",
            started_at=NOW,
            finished_at=NOW,
            findings=[error],
            ready=False,
        ),
        baseline,
        now=NOW,
    )
    log = json.loads(render_sarif(report))
    jsonschema.validate(log, SCHEMA)
    (result,) = log["runs"][0]["results"]
    assert result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == (
        "config/zoho/field.json"
    )
    assert result["level"] == "none"
    assert result["suppressions"] == [{"kind": "external", "justification": "accepted in baseline"}]


def test_junit_parses_with_exact_counts() -> None:
    xml = JUnitXml.fromstring(render_junit(sample_report()))
    assert xml.tests == 3
    assert xml.failures == 2
    assert xml.skipped == 0
    cases = [case for suite in xml for case in suite]
    assert [case.name for case in cases] == [item.id for item in sample_report().findings]
    assert all(case.classname.startswith("release.") for case in cases)


def test_junit_marks_suppressed_as_skipped() -> None:
    error = _finding("removal_review", "field:X")
    baseline = Baseline(
        suppressions=[
            BaselineEntry(id=error.id, reason="Accepted.", approver="sam", expires=NOW.date())
        ]
    )
    report = apply_baseline(
        Report.build(
            module="release",
            run_id="run-0001",
            started_at=NOW,
            finished_at=NOW,
            findings=[error],
            ready=False,
        ),
        baseline,
        now=NOW,
    )
    xml = JUnitXml.fromstring(render_junit(report))
    assert xml.tests == 1
    assert xml.failures == 0
    assert xml.skipped == 1


def test_cli_sarif_and_junit_formats(tmp_path: Path) -> None:
    fixture = ROOT / "tests" / "golden" / "legacy" / "release" / "inputs" / "examples.json"
    sarif = runner.invoke(app, ["release", "diff", str(fixture), "--format", "sarif"])
    assert sarif.exit_code == 0
    log = json.loads(sarif.output)
    jsonschema.validate(log, SCHEMA)
    assert len(log["runs"][0]["results"]) == 6
    junit = runner.invoke(app, ["release", "diff", str(fixture), "--format", "junit"])
    assert junit.exit_code == 0
    assert JUnitXml.fromstring(junit.output).tests == 6
    assert tmp_path.is_dir()
