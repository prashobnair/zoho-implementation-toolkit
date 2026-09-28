"""Workflow port tests: exact trace values and engine options."""

from __future__ import annotations

import json
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from zohokit.modules.workflow.engine import analyze
from zohokit.modules.workflow.models import WorkflowInput

ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _examples() -> WorkflowInput:
    path = ROOT / "legacy" / "zoho-workflow-rule-testbench" / "examples.json"
    return WorkflowInput.model_validate(json.loads(path.read_text()))


def test_examples_exact_findings() -> None:
    analysis = analyze(_examples())
    assert analysis.ready is False
    assert [finding.code for finding in analysis.findings] == [
        "missing_owner",
        "duplicate_followup",
        "cycle_detected",
    ]
    assert [finding.entity_id for finding in analysis.findings] == [
        "assign-new",
        "followup-b",
        "stage_changed",
    ]
    assert analysis.legacy["external_actions"] == 0
    assert analysis.legacy["state"]["owner"] is None


def test_clean_rules_ready() -> None:
    inputs = WorkflowInput(
        rules=[
            {
                "id": "owner",
                "event": "deal_created",
                "action": "assign_owner",
                "value": "fictional-team",
            }
        ],
        record={"id": "x", "stage": "new"},
    )
    analysis = analyze(inputs)
    assert analysis.ready is True
    assert analysis.legacy["state"] == {"id": "x", "stage": "new", "owner": "fictional-team"}


def test_step_limit_surfaced() -> None:
    inputs = _examples()
    inputs.max_steps = 2
    analysis = analyze(inputs)
    assert any(finding.code == "step_limit" for finding in analysis.findings)


def _ids(inputs: WorkflowInput) -> list[str]:
    return sorted(finding.id for finding in analyze(inputs).findings)


@given(st.data())
def test_ids_stable_under_record_key_shuffle(data: st.DataObject) -> None:
    """Record key order is not identifying: shuffled keys keep every ID."""
    inputs = _examples()
    keys = list(inputs.record.keys())
    order = data.draw(st.permutations(range(len(keys))))
    shuffled = WorkflowInput(
        rules=inputs.rules,
        record={keys[index]: inputs.record[keys[index]] for index in order},
        initial_event=inputs.initial_event,
    )
    assert _ids(shuffled) == _ids(inputs)


def test_ids_stable_when_rule_added() -> None:
    inputs = _examples()
    before = set(_ids(inputs))
    extended = WorkflowInput(
        rules=[
            *inputs.rules,
            {
                "id": "never",
                "event": "followup_due",
                "when": {"stage": "no-such-stage"},
                "action": "assign_owner",
                "value": "nobody",
            },
        ],
        record=dict(inputs.record),
        initial_event=inputs.initial_event,
    )
    assert before <= set(_ids(extended))


def test_ids_unique() -> None:
    ids = _ids(_examples())
    assert len(ids) == len(set(ids)) == 3
