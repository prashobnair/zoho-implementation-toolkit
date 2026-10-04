"""Baseline suppression file tests (accepted findings with expiry)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from zohokit.cli import app
from zohokit.core.baseline import (
    Baseline,
    BaselineEntry,
    BaselineError,
    active_ids,
    apply_baseline,
    load_baseline,
)
from zohokit.core.findings import Finding, Report, Severity
from zohokit.core.ids import finding_id

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parent.parent.parent
runner = CliRunner()


def _finding(code: str = "removal_review", entity_id: str = "field:Deals.External_Ref") -> Finding:
    return Finding.create(
        module="release",
        code=code,
        severity=Severity.ERROR,
        entity="manifest",
        entity_id=entity_id,
        message=f"{code}: {entity_id}",
        discriminator=entity_id,
    )


def _report(*findings: Finding) -> Report:
    return Report.build(
        module="release",
        run_id="run-0001",
        started_at=NOW,
        finished_at=NOW,
        findings=list(findings),
        ready=not findings,
    )


def _baseline_file(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / ".zohokit-baseline.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_valid_baseline(tmp_path: Path) -> None:
    finding = _finding()
    path = _baseline_file(
        tmp_path,
        {
            "version": 1,
            "suppressions": [
                {
                    "id": finding.id,
                    "reason": "Accepted for the October cutover.",
                    "approver": "release-manager",
                    "expires": "2026-10-31",
                }
            ],
        },
    )
    baseline = load_baseline(path)
    assert baseline.suppressions[0].id == finding.id
    assert baseline.suppressions[0].expires.isoformat() == "2026-10-31"


def test_missing_reason_is_an_error(tmp_path: Path) -> None:
    path = _baseline_file(
        tmp_path,
        {
            "version": 1,
            "suppressions": [
                {"id": "a" * 24, "approver": "release-manager", "expires": "2026-10-31"}
            ],
        },
    )
    with pytest.raises(BaselineError, match="reason"):
        load_baseline(path)


def test_missing_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(BaselineError, match="cannot read"):
        load_baseline(tmp_path / "absent.json")


def test_suppressed_finding_does_not_block_ready() -> None:
    finding = _finding()
    baseline = Baseline(
        suppressions=[
            BaselineEntry(
                id=finding.id,
                reason="Accepted for the October cutover.",
                approver="release-manager",
                expires=NOW.date(),
            )
        ]
    )
    suppressed = apply_baseline(_report(finding), baseline, now=NOW)
    assert suppressed.ready is True
    assert suppressed.findings[0].suppressed is True
    assert suppressed.summary.suppressed == 1
    assert suppressed.summary.error == 1


def test_expired_suppression_reactivates() -> None:
    finding = _finding()
    baseline = Baseline(
        suppressions=[
            BaselineEntry(
                id=finding.id,
                reason="Accepted for the September cutover.",
                approver="release-manager",
                expires=_day_before(NOW),
            )
        ]
    )
    revived = apply_baseline(_report(finding), baseline, now=NOW)
    assert revived.ready is False
    assert revived.findings[0].suppressed is False
    assert active_ids(baseline, now=NOW) == set()


def _day_before(moment: datetime) -> date:
    """The calendar day before ``moment`` (baseline expiry is date precision)."""
    return (moment - timedelta(days=1)).date()


def test_partial_suppression_stays_blocked() -> None:
    first, second = _finding(entity_id="a"), _finding(entity_id="b")
    assert first.id != second.id
    baseline = Baseline(
        suppressions=[
            BaselineEntry(
                id=first.id,
                reason="Accepted for the October cutover.",
                approver="release-manager",
                expires=NOW.date(),
            )
        ]
    )
    report = apply_baseline(_report(first, second), baseline, now=NOW)
    assert report.ready is False
    assert [item.suppressed for item in report.findings] == [True, False]


def test_finding_ids_are_stable_content_keys() -> None:
    assert _finding().id == finding_id(
        "release",
        "removal_review",
        "manifest",
        "field:Deals.External_Ref",
        "field:Deals.External_Ref",
    )


def test_cli_baseline_suppresses_blocking_findings(tmp_path: Path) -> None:
    fixture = ROOT / "tests" / "golden" / "legacy" / "release" / "inputs" / "examples.json"
    plain = runner.invoke(app, ["release", "diff", str(fixture), "--strict"])
    assert plain.exit_code == 2
    ids = [item["id"] for item in json.loads(plain.output)["findings"]]
    assert len(ids) == 6
    baseline = tmp_path / ".zohokit-baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "version": 1,
                "suppressions": [
                    {
                        "id": item,
                        "reason": "Accepted for the October cutover.",
                        "approver": "release-manager",
                        "expires": "2099-01-01",
                    }
                    for item in ids
                ],
            }
        ),
        encoding="utf-8",
    )
    accepted = runner.invoke(
        app, ["release", "diff", str(fixture), "--strict", "--baseline", str(baseline)]
    )
    assert accepted.exit_code == 0
    payload = json.loads(accepted.output)
    assert payload["ready"] is True
    assert payload["summary"]["suppressed"] == 6
    assert all(item["suppressed"] for item in payload["findings"])


def test_cli_baseline_missing_reason_exits_1(tmp_path: Path) -> None:
    fixture = ROOT / "tests" / "golden" / "legacy" / "release" / "inputs" / "examples.json"
    baseline = _baseline_file(
        tmp_path,
        {"version": 1, "suppressions": [{"id": "a" * 24, "expires": "2099-01-01"}]},
    )
    result = runner.invoke(app, ["release", "diff", str(fixture), "--baseline", str(baseline)])
    assert result.exit_code == 1
