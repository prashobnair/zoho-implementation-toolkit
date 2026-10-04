"""Report diff tests: new, resolved and changed findings by stable ID."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from zohokit.cli import app
from zohokit.core.diff_reports import (
    diff_reports,
    render_diff_json,
    render_diff_markdown,
    render_diff_table,
)
from zohokit.core.findings import Finding, Report, Severity

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
runner = CliRunner()


def _finding(
    code: str, entity_id: str, severity: Severity = Severity.ERROR, **extra: object
) -> Finding:
    evidence = {key: str(value) for key, value in extra.items()}
    return Finding.create(
        module="release",
        code=code,
        severity=severity,
        entity="manifest",
        entity_id=entity_id,
        message=f"{code}: {entity_id}",
        evidence=evidence,
        discriminator=entity_id,
    )


def _report(*findings: Finding, run_id: str = "run-0001") -> Report:
    return Report.build(
        module="release",
        run_id=run_id,
        started_at=NOW,
        finished_at=NOW,
        findings=list(findings),
        ready=not findings,
    )


def test_new_resolved_and_unchanged() -> None:
    kept = _finding("removal_review", "field:Deals.External_Ref")
    gone = _finding("missing_dependency", "workflow:Notify", extra_dep="x")
    fresh = _finding("field_type_change", "field:Deals.Amount")
    diff = diff_reports(_report(kept, gone, run_id="a"), _report(kept, fresh, run_id="b"))
    assert [item.id for item in diff.new] == [fresh.id]
    assert [item.id for item in diff.resolved] == [gone.id]
    assert diff.changed == ()
    assert [item.id for item in diff.new_errors] == [fresh.id]


def test_changed_when_content_differs_under_same_id() -> None:
    old = _finding("removal_review", "field:X", severity=Severity.ERROR)
    new = Finding.create(
        module="release",
        code="removal_review",
        severity=Severity.REVIEW,
        entity="manifest",
        entity_id="field:X",
        message="removal_review: field:X",
        discriminator="field:X",
    )
    assert old.id == new.id
    diff = diff_reports(_report(old, run_id="a"), _report(new, run_id="b"))
    assert diff.new == () and diff.resolved == ()
    assert [(before.id, after.id) for before, after in diff.changed] == [(old.id, new.id)]


def test_json_shape_has_exact_ids() -> None:
    fresh = _finding("field_type_change", "field:Deals.Amount")
    payload = json.loads(
        render_diff_json(
            _report(run_id="a"),
            _report(fresh, run_id="b"),
            diff_reports(_report(run_id="a"), _report(fresh, run_id="b")),
        )
    )
    assert payload["summary"] == {"new": 1, "resolved": 0, "changed": 0, "new_errors": 1}
    assert payload["new"][0]["id"] == fresh.id
    assert payload["before_run_id"] == "a"


def test_table_and_markdown_render_counts() -> None:
    fresh = _finding("field_type_change", "field:Deals.Amount")
    diff = diff_reports(_report(run_id="a"), _report(fresh, run_id="b"))
    table = render_diff_table(diff)
    assert "new: 1  resolved: 0  changed: 0  new errors: 1" in table
    assert fresh.id in table
    markdown = render_diff_markdown(_report(run_id="a"), _report(fresh, run_id="b"), diff)
    assert "**1 new**, **0 resolved**, **0 changed**" in markdown


def test_cli_diff_reports_exit_codes(tmp_path: Path) -> None:
    fresh = _finding("field_type_change", "field:Deals.Amount")
    before = tmp_path / "a.json"
    after = tmp_path / "b.json"
    before.write_text(_report(run_id="a").model_dump_json(indent=2), encoding="utf-8")
    after.write_text(_report(fresh, run_id="b").model_dump_json(indent=2), encoding="utf-8")
    ok = runner.invoke(app, ["diff-reports", str(before), str(after)])
    assert ok.exit_code == 0
    blocked = runner.invoke(app, ["diff-reports", str(before), str(after), "--strict"])
    assert blocked.exit_code == 2
    same = runner.invoke(app, ["diff-reports", str(after), str(after), "--strict"])
    assert same.exit_code == 0
    broken = runner.invoke(app, ["diff-reports", str(before), str(tmp_path / "absent.json")])
    assert broken.exit_code == 1
