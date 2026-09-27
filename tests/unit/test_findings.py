"""Unit tests for findings and the report envelope (TK-CORE-1 scaffold)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

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


def test_mode_and_source_kind_are_literal() -> None:
    now = datetime(2026, 9, 27, tzinfo=UTC)
    live = Report.build(
        module="migration",
        run_id="run-3",
        started_at=now,
        finished_at=now,
        findings=[],
        ready=True,
        mode="live_read",
        source=ReportSource(kind="zoho", dc="in", org_fingerprint="abc123"),
    )
    assert live.mode == "live_read"
    assert live.source.kind == "zoho"
    with pytest.raises(ValidationError):
        Report.build(
            module="migration",
            run_id="run-4",
            started_at=now,
            finished_at=now,
            findings=[],
            ready=True,
            mode="live",  # type: ignore[arg-type]
        )
    with pytest.raises(ValidationError):
        ReportSource(kind="csv")  # type: ignore[arg-type]


def test_finding_create_computes_exact_id() -> None:
    finding = Finding.create(
        module="migration",
        code="orphan_person",
        severity=Severity.ERROR,
        entity="deals",
        entity_id="d-2",
        message="Deal references a missing person.",
        evidence={"person_id": "p-9"},
    )
    assert finding.id == "c0800b41f6fb8d7ead02b9a3"
    assert finding.evidence == {"person_id": "p-9"}


def test_finding_id_validator_rejects_free_text() -> None:
    base = {
        "module": "migration",
        "code": "orphan_person",
        "severity": Severity.ERROR,
        "entity": "deals",
        "entity_id": "d-2",
        "message": "x",
    }
    for bad_id in (
        "",
        "xyz",
        "c0800b41f6fb8d7ead02b9a",
        "C0800B41F6FB8D7EAD02B9A3",
        "c0800b41f6fb8d7ead02b9a3 ",
    ):
        with pytest.raises(ValidationError):
            Finding(id=bad_id, **base)  # type: ignore[arg-type]


@given(
    st.text(min_size=1, max_size=12),
    st.text(min_size=1, max_size=12),
    st.text(min_size=1, max_size=12),
    st.text(min_size=1, max_size=12),
    st.dictionaries(st.text(max_size=6), st.integers(), max_size=3),
    st.dictionaries(st.text(max_size=6), st.integers(), max_size=3),
)
def test_create_identity_property(
    module: str,
    code: str,
    entity: str,
    entity_id: str,
    evidence_a: dict[str, Any],
    evidence_b: dict[str, Any],
) -> None:
    """TK-CORE-2: evidence never changes the id; any identity part can."""
    first = Finding.create(
        module=module,
        code=code,
        severity=Severity.ERROR,
        entity=entity,
        entity_id=entity_id,
        message="m",
        evidence=evidence_a,
    )
    second = Finding.create(
        module=module,
        code=code,
        severity=Severity.ERROR,
        entity=entity,
        entity_id=entity_id,
        message="m",
        evidence=evidence_b,
    )
    assert first.id == second.id
    changed = Finding.create(
        module=module,
        code=code,
        severity=Severity.ERROR,
        entity=entity,
        entity_id=entity_id + "!",
        message="m",
        evidence=evidence_a,
    )
    assert changed.id != first.id
