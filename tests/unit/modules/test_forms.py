"""Forms port tests: TK-FIX-5 chained visibility, cycles, hidden answers."""

from __future__ import annotations

import json
from pathlib import Path

from hypothesis import assume, given
from hypothesis import strategies as st

from zohokit.core.findings import Severity
from zohokit.core.ids import finding_id
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
    assert {finding.code for finding in analysis.findings} == {"visibility_cycle"}
    assert all(finding.severity is Severity.INFO for finding in analysis.findings)
    assert legacy["all_pass"] is True  # both sides equally unevaluable
    assert analysis.ready is True


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
    (mismatch,) = [finding for finding in analysis.findings if finding.code == "parity_mismatch"]
    assert mismatch.severity is Severity.ERROR
    assert mismatch.entity_id == "delivery_calculation:estimate"
    assert mismatch.id == finding_id(
        "forms",
        "parity_mismatch",
        "case",
        "delivery_calculation:estimate",
        "delivery_calculation:estimate",
    )
    assert mismatch.evidence == {
        "case": "delivery_calculation",
        "field": "estimate",
        "source": "600",
        "target": "203",
    }


def test_corrected_target_has_issues_but_matches() -> None:
    """all_pass with remaining issues: matching outputs, agreed issues are info."""
    data = json.loads((ROOT / "legacy" / "zoho-forms-parity-checker" / "examples.json").read_text())
    data["target_fields"][4]["operation"] = "multiply"
    analysis = analyze(FormsInput.model_validate(data))
    assert to_legacy_dict(analysis)["all_pass"] is True
    assert analysis.ready is True
    assert {finding.code for finding in analysis.findings} == {"required_missing"}
    assert all(finding.severity is Severity.INFO for finding in analysis.findings)


def test_one_sided_difference_blocks() -> None:
    """An issue on one side only is an error and fails the case."""
    fields = [{"name": "a", "type": "text", "required": True}]
    inputs = FormsInput(
        source_fields=fields,
        target_fields=[{"name": "a", "type": "text"}],
        cases=[{"name": "case-1", "answers": {}}],
    )
    analysis = analyze(inputs)
    assert to_legacy_dict(analysis)["all_pass"] is False
    assert analysis.ready is False
    (finding,) = analysis.findings
    assert (finding.code, finding.severity, finding.entity_id) == (
        "required_missing",
        Severity.ERROR,
        "case-1:source:a",
    )


def _examples_input() -> FormsInput:
    data = json.loads((ROOT / "legacy" / "zoho-forms-parity-checker" / "examples.json").read_text())
    return FormsInput.model_validate(data)


def _ids(inputs: FormsInput) -> list[str]:
    return sorted(finding.id for finding in analyze(inputs).findings)


@given(st.data())
def test_ids_stable_under_case_shuffle(data: st.DataObject) -> None:
    inputs = _examples_input()
    order = data.draw(st.permutations(range(len(inputs.cases))))
    shuffled = FormsInput(
        source_fields=inputs.source_fields,
        target_fields=inputs.target_fields,
        cases=[inputs.cases[index] for index in order],
    )
    assert _ids(shuffled) == _ids(inputs)


@given(st.text(min_size=1, max_size=12))
def test_ids_stable_when_case_added(extra: str) -> None:
    inputs = _examples_input()
    names = {str(case.get("name", "")) for case in inputs.cases}
    assume(extra and extra not in names)
    before = set(_ids(inputs))
    extended = FormsInput(
        source_fields=inputs.source_fields,
        target_fields=inputs.target_fields,
        cases=[*inputs.cases, {"name": extra, "answers": {}}],
    )
    assert before <= set(_ids(extended))


def test_ids_unique() -> None:
    ids = _ids(_examples_input())
    assert len(ids) == len(set(ids))
