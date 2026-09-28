"""Migration port tests: exact legacy parity values, TK-FIX-7, frozen clock."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hypothesis import assume, given
from hypothesis import strategies as st

from zohokit.core.context import RunContext
from zohokit.modules.migration.engine import analyze, run
from zohokit.modules.migration.models import MigrationInput
from zohokit.reports import render_json

ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _examples() -> MigrationInput:
    path = ROOT / "tests" / "golden" / "legacy" / "migration" / "inputs" / "examples.json"
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
    assert render_json(run(inputs, ctx=RunContext(now=now))) == render_json(
        run(inputs, ctx=RunContext(now=now))
    )
    assert len({finding.id for finding in run(inputs, ctx=RunContext(now=now)).findings}) == 4


def _ordered_sample() -> dict[str, Any]:
    """Findings without first-seen survivors: safe for shuffle properties."""
    path = ROOT / "tests" / "golden" / "legacy" / "migration" / "inputs" / "examples.json"
    base: dict[str, Any] = json.loads(path.read_text())
    base["people"] = [base["people"][0], base["people"][2]]
    return base


def _ids(inputs: MigrationInput) -> list[str]:
    return sorted(finding.id for finding in analyze(inputs).findings)


@given(st.data())
def test_ids_stable_under_row_shuffle(data: st.DataObject) -> None:
    base = _ordered_sample()
    payload = {
        entity: [rows[index] for index in data.draw(st.permutations(range(len(rows))))]
        for entity, rows in base.items()
        if isinstance(rows, list)
    }
    payload["stage_mapping"] = base["stage_mapping"]
    assert _ids(MigrationInput.model_validate(payload)) == _ids(MigrationInput.model_validate(base))


@given(st.text(min_size=1, max_size=8))
def test_ids_stable_when_row_added(extra_id: str) -> None:
    base = _ordered_sample()
    assume(
        extra_id
        not in {row.get("id") for rows in base.values() if isinstance(rows, list) for row in rows}
    )
    before = set(_ids(MigrationInput.model_validate(base)))
    base["organizations"].append({"id": extra_id, "name": "Extra"})
    assert before <= set(_ids(MigrationInput.model_validate(base)))


def test_ids_unique() -> None:
    ids = _ids(_examples())
    assert len(ids) == len(set(ids)) == 4
