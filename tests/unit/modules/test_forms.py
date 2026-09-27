"""Forms port tests: TK-FIX-5 chained visibility, cycles, hidden answers."""

from __future__ import annotations

import json
from pathlib import Path

from zohokit.core.findings import Severity
from zohokit.modules.forms.engine import analyze
from zohokit.modules.forms.models import FormsInput
from zohokit.modules.forms.report import to_legacy_dict

ROOT = Path(__file__).resolve().parent.parent.parent.parent

CHAINED_FIELDS = [
    {"name": "mode", "type": "select", "options": ["x", "y"]},
    {"name": "mid", "type": "text", "visible_if": {"mode": "x"}},
    {"name": "leaf", "type": "text", "visible_if": {"mid": "shown"}},
]


def _inputs(fields: list[dict], answers: dict) -> FormsInput:
    return FormsInput(
        source_fields=fields,
        target_fields=fields,
        cases=[{"name": "case-1", "answers": answers}],
    )


def test_hidden_parent_hides_child_tk_fix_5() -> None:
    """mid is hidden (mode != x), so leaf stays hidden although mid matches."""
    analysis = analyze(_inputs(CHAINED_FIELDS, {"mode": "y", "mid": "shown", "leaf": "hi"}))
    assert to_legacy_dict(analysis)["cases"][0]["source"]["output"] == {"mode": "y"}
    infos = [finding for finding in analysis.findings if finding.code == "answer_for_hidden_field"]
    assert [(finding.severity, finding.entity_id) for finding in infos] == [
        (Severity.INFO, "case-1:source:mid"),
        (Severity.INFO, "case-1:source:leaf"),
        (Severity.INFO, "case-1:target:mid"),
        (Severity.INFO, "case-1:target:leaf"),
    ]
    assert analysis.ready is True  # outputs still match; infos never block


def test_visible_chain_evaluates() -> None:
    analysis = analyze(_inputs(CHAINED_FIELDS, {"mode": "x", "mid": "shown", "leaf": "hi"}))
    assert to_legacy_dict(analysis)["cases"][0]["source"]["output"] == {
        "mode": "x",
        "mid": "shown",
        "leaf": "hi",
    }
    assert analysis.findings == ()


def test_visibility_cycle_is_error() -> None:
    fields = [
        {"name": "a", "type": "text", "visible_if": {"b": "1"}},
        {"name": "b", "type": "text", "visible_if": {"a": "1"}},
    ]
    analysis = analyze(_inputs(fields, {}))
    legacy = to_legacy_dict(analysis)
    assert legacy["cases"][0]["source"]["issues"] == [
        {"field": "a", "code": "visibility_cycle"},
        {"field": "b", "code": "visibility_cycle"},
    ]
    errors = [finding for finding in analysis.findings if finding.code == "visibility_cycle"]
    assert [(finding.severity, finding.entity_id) for finding in errors] == [
        (Severity.ERROR, "source:a"),
        (Severity.ERROR, "source:b"),
        (Severity.ERROR, "target:a"),
        (Severity.ERROR, "target:b"),
    ]
    assert legacy["all_pass"] is True  # both sides equally empty
    assert analysis.ready is False  # error findings block


def test_invalid_reference_preserved() -> None:
    fields = [{"name": "a", "type": "text", "visible_if": {"nope": "1"}}]
    analysis = analyze(_inputs(fields, {"a": "hi"}))
    legacy = to_legacy_dict(analysis)
    assert legacy["cases"][0]["source"]["issues"] == [
        {"field": "a", "code": "invalid_visibility_reference"}
    ]
    assert legacy["cases"][0]["source"]["output"] == {}


def test_examples_mismatch_parity_shape() -> None:
    data = json.loads((ROOT / "legacy" / "zoho-forms-parity-checker" / "examples.json").read_text())
    analysis = analyze(FormsInput.model_validate(data))
    assert analysis.ready is False
    failing = to_legacy_dict(analysis)["cases"][1]
    assert failing["pass"] is False
    assert failing["source"]["output"]["estimate"] == "600"
    assert failing["target"]["output"]["estimate"] == "203"
