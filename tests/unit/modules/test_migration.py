"""Migration port tests: exact legacy parity values, TK-FIX-7, frozen clock."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from zohokit.core.context import RunContext
from zohokit.modules.migration.engine import analyze, run
from zohokit.modules.migration.models import MigrationInput
from zohokit.reports import render_json

ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _examples() -> MigrationInput:
    path = ROOT / "legacy" / "zoho-crm-migration-auditor" / "examples.json"
    return MigrationInput.model_validate(json.loads(path.read_text()))


def test_examples_exact_issues() -> None:
    analysis = analyze(_examples())
    assert analysis.ready is False
    assert {issue["code"] for issue in analysis.legacy["issues"]} == {
        "possible_duplicate",
        "orphan_organization",
        "orphan_person",
        "unmapped_stage",
    }
    assert analysis.legacy["issues"][0] == {
        "severity": "review",
        "entity": "people",
        "source_id": "p-2",
        "code": "possible_duplicate",
        "detail": "Email matches source person p-1",
    }
    assert analysis.legacy["import_order"] == ["organizations", "people", "deals", "activities"]
    assert analysis.legacy["target_preview_counts"] is None


def test_clean_sample_ready() -> None:
    inputs = _examples()
    inputs.people = inputs.people[:1]
    inputs.deals = inputs.deals[:1]
    analysis = analyze(inputs)
    assert analysis.ready is True
    assert analysis.legacy["issues"] == []
    assert analysis.legacy["target_preview_counts"] == analysis.legacy["source_counts"]


def test_no_unused_imports_tk_fix_7() -> None:
    source = (ROOT / "src" / "zohokit" / "modules" / "migration" / "engine.py").read_text()
    assert "Counter" not in source
    assert "defaultdict" not in source


def test_frozen_clock_byte_identical() -> None:
    inputs = _examples()
    now = datetime(2026, 9, 27, 12, tzinfo=UTC)
    first = render_json(run(inputs, ctx=RunContext(now=now)))
    second = render_json(run(inputs, ctx=RunContext(now=now)))
    assert first == second
    assert len({finding.id for finding in run(inputs, ctx=RunContext(now=now)).findings}) == 4
