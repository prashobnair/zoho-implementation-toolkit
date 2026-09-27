"""Unit tests for findings and the report envelope (TK-CORE-1 scaffold)."""

from __future__ import annotations

from datetime import UTC, datetime

from zohokit.core.findings import (
    Finding,
    Report,
    ReportSource,
    Severity,
    SideEffects,
    sort_findings,
)
from zohokit.core.ids import finding_id


def _finding(
    code: str = "orphan_person",
    severity: Severity = Severity.ERROR,
    entity: str = "deals",
    entity_id: str = "d-2",
    module: str = "migration",
) -> Finding:
    return Finding(
        id=finding_id(module, code, entity, entity_id),
        module=module,
        code=code,
        severity=severity,
        entity=entity,
        entity_id=entity_id,
        message="test finding",
    )


def test_sort_findings_orders_by_severity_then_identity() -> None:
    info = _finding(code="a_info", severity=Severity.INFO, entity_id="z-9")
    error = _finding(code="z_error", severity=Severity.ERROR, entity_id="a-1")
    review = _finding(code="m_review", severity=Severity.REVIEW, entity_id="m-1")
    assert sort_findings([info, error, review]) == [error, review, info]


def test_report_build_derives_summary_and_sorts() -> None:
    now = datetime(2026, 9, 27, tzinfo=UTC)
    report = Report.build(
        module="migration",
        run_id="run-1",
        started_at=now,
        finished_at=now,
        findings=[_finding(severity=Severity.WARNING), _finding(severity=Severity.ERROR)],
        ready=False,
    )
    assert report.summary.error == 1
    assert report.summary.warning == 1
    assert report.summary.review == 0
    assert report.findings[0].severity is Severity.ERROR
    assert report.ready is False


def test_report_carries_full_envelope() -> None:
    now = datetime(2026, 9, 27, tzinfo=UTC)
    report = Report.build(
        module="migration",
        run_id="run-2",
        started_at=now,
        finished_at=now,
        findings=[],
        ready=True,
        mode="offline",
        source=ReportSource(kind="fixture", dc="in", org_fingerprint="abc123"),
        inputs_sha256="0" * 64,
        artifacts={"html": "reports/migration.html"},
        side_effects=SideEffects(),
    )
    assert report.schema_version == "2"
    assert report.tool == "zohokit"
    assert report.source.org_fingerprint == "abc123"
    assert report.inputs_sha256 == "0" * 64
    assert report.artifacts == {"html": "reports/migration.html"}
    assert report.side_effects.external_writes == 0
    assert report.side_effects.messages_sent == 0
