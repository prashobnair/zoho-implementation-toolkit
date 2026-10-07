"""Renderer tests incl. snapshots (TK-CORE-1 snapshot, TK-CORE-8)."""

from __future__ import annotations

from datetime import datetime

from syrupy.assertion import SnapshotAssertion

from zohokit.core.findings import Finding, Report, ReportSource, Severity, SideEffects
from zohokit.core.ids import finding_id
from zohokit.reports import render_html, render_json, render_junit, render_markdown, render_table

FIXED_START_ISO = "2026-09-27T06:30:00Z"


def sample_report() -> Report:
    """A fixed two-finding report shared by renderer tests."""
    started = datetime.fromisoformat(FIXED_START_ISO)
    findings = [
        Finding(
            id=finding_id("migration", "orphan_person", "deals", "d-2"),
            module="migration",
            code="orphan_person",
            severity=Severity.ERROR,
            entity="deals",
            entity_id="d-2",
            message="Deal references a person ID that is not present in the export.",
            evidence={"person_id": "p-9"},
            remediation="Add the person to the export or remove the deal.",
        ),
        Finding(
            id=finding_id("migration", "possible_duplicate", "people", "p-2"),
            module="migration",
            code="possible_duplicate",
            severity=Severity.REVIEW,
            entity="people",
            entity_id="p-2",
            message="Two people share a normalized email.",
        ),
    ]
    return Report.build(
        module="migration",
        run_id="run-0001",
        started_at=started,
        finished_at=started,
        findings=findings,
        ready=False,
        source=ReportSource(kind="fixture", dc="in", org_fingerprint="abc123"),
        inputs_sha256="0" * 64,
        artifacts={"html": "reports/migration.html"},
        side_effects=SideEffects(),
    )


def test_render_json_snapshot(snapshot: SnapshotAssertion) -> None:
    assert render_json(sample_report()) == snapshot


def test_render_html_golden(snapshot: SnapshotAssertion) -> None:
    assert render_html(sample_report()) == snapshot


def test_render_html_is_self_contained() -> None:
    html = render_html(sample_report())
    assert "<!DOCTYPE html>" in html
    assert "http://" not in html and "https://" not in html
    assert 'id="severity-filter"' in html
    assert 'id="code-filter"' in html
    assert "@media print" in html
    assert "prefers-color-scheme" in html
    assert "<details>" in html
    assert "orphan_person" in html


def test_render_html_escapes_evidence() -> None:
    report = sample_report()
    evil = Finding(
        id=finding_id("migration", "x", "deals", "d-1"),
        module="migration",
        code="x",
        severity=Severity.INFO,
        entity="deals",
        entity_id="d-1",
        message="<script>alert(1)</script>",
        evidence={"k": "<b>bold</b>"},
    )
    rebuilt = Report.build(
        module="migration",
        run_id="run-0001",
        started_at=report.started_at,
        finished_at=report.finished_at,
        findings=[evil],
        ready=True,
    )
    html = render_html(rebuilt)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_table_lists_findings() -> None:
    table = render_table(sample_report())
    assert "orphan_person" in table
    assert "possible_duplicate" in table
    assert "error" in table


def test_render_markdown_structure() -> None:
    markdown = render_markdown(sample_report())
    assert markdown.startswith("# zohokit migration report")
    assert "NOT READY" in markdown
    assert "| Severity | Entity | Code | Message |" in markdown
    assert "`orphan_person`" in markdown


def test_render_markdown_escapes_cells() -> None:
    report = sample_report()
    tricky = Finding(
        id=finding_id("migration", "x", "deals", "d-1"),
        module="migration",
        code="x",
        severity=Severity.INFO,
        entity="deals",
        entity_id="d-1",
        message="a|b\nc",
    )
    rebuilt = Report.build(
        module="migration",
        run_id=report.run_id,
        started_at=report.started_at,
        finished_at=report.finished_at,
        findings=[tricky],
        ready=True,
    )
    row = [line for line in render_markdown(rebuilt).splitlines() if "`x`" in line]
    assert row == ["| info | deals/d-1 | `x` | a\\|b<br>c |"]


def _simulated_report() -> Report:
    """A workflow report carrying the reachable simulation block."""
    report = sample_report()
    return Report.build(
        module="workflow",
        run_id=report.run_id,
        started_at=report.started_at,
        finished_at=report.finished_at,
        findings=[],
        ready=True,
        simulation={
            "trace": [
                {
                    "step": "s1",
                    "rule": "promote",
                    "action": "field_update",
                    "day": 0,
                    "caused_by": "e0",
                    "fields_changed": ["Stage"],
                }
            ],
            "ledger": [],
            "external_actions": 0,
            "days_elapsed": 0,
        },
    )


def test_render_markdown_lists_the_simulation_trace() -> None:
    markdown = render_markdown(_simulated_report())
    assert "## Simulation trace" in markdown
    assert "| Step | Rule | Action | Day | Caused by | Fields changed |" in markdown
    assert "| s1 | promote | field_update | 0 | e0 | Stage |" in markdown
    assert "External actions: 0" in markdown


def test_render_markdown_without_simulation_has_no_trace_section() -> None:
    assert "## Simulation trace" not in render_markdown(sample_report())


def test_render_html_lists_the_simulation_trace() -> None:
    html = render_html(_simulated_report())
    assert "<h2>Simulation trace</h2>" in html
    assert "<td>s1</td>" in html
    assert "<td>promote</td>" in html
    assert "<td>field_update</td>" in html
    assert "External actions: 0" in html


def test_render_html_without_simulation_has_no_trace_section() -> None:
    assert "<h2>Simulation trace</h2>" not in render_html(sample_report())


def test_render_junit_without_coverage_stays_per_finding() -> None:
    xml = render_junit(sample_report())
    assert 'tests="2"' in xml
    assert xml.count("<testcase") == 2
