"""Workflow language v2 + deterministic simulator + ledger (TK-WF-F1..F3)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from zohokit.core.ids import canonical_json
from zohokit.modules.workflow.engine import analyze
from zohokit.modules.workflow.language import (
    V2_ACTIONS,
    V2_EVENTS,
    V2_OPERATORS,
    parse_ruleset,
    rule_schema,
)
from zohokit.modules.workflow.ledger import SideEffectLedger
from zohokit.modules.workflow.models import WorkflowInput
from zohokit.modules.workflow.simulator import simulate_v2


def _v2_rule(rule_id: str, **over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": rule_id,
        "event": {"type": "record_created"},
        "actions": [{"type": "assign_owner", "owner": "regional-manager"}],
    }
    base.update(over)
    return base


def test_language_covers_every_event_operator_action() -> None:
    assert set(V2_EVENTS) == {
        "record_created",
        "record_edited",
        "field_changed",
        "stage_changed",
        "scheduled",
        "date_field_reached",
    }
    assert set(V2_OPERATORS) == {
        "eq",
        "neq",
        "in",
        "not_in",
        "gt",
        "lt",
        "is_empty",
        "changed_to",
        "changed_from",
    }
    assert set(V2_ACTIONS) == {
        "field_update",
        "assign_owner",
        "create_task",
        "send_email",
        "webhook",
        "function",
    }
    for event in V2_EVENTS:
        extra: dict[str, object] = {}
        if event in ("field_changed", "date_field_reached"):
            extra["field"] = "Stage"
        if event in ("scheduled", "date_field_reached"):
            extra["offset_days"] = 2
        kind, parsed = parse_ruleset([_v2_rule(f"r-{event}", event={"type": event, **extra})])
        assert kind == "v2"
        assert parsed.rules[0].event.type == event
    for action in V2_ACTIONS:
        payload: dict[str, object] = {"type": action}
        if action == "field_update":
            payload.update({"field": "Stage", "value": "Negotiation"})
        elif action == "assign_owner":
            payload.update({"owner": "regional-manager"})
        elif action == "send_email":
            payload.update({"template": "owner-alert"})
        elif action == "webhook":
            payload.update({"url": "https://example.invalid/hooks/billing"})
        elif action == "function":
            payload.update({"function_name": "score_lead"})
        elif action == "create_task":
            payload.update({"value": "Follow up"})
        kind, _ = parse_ruleset([_v2_rule(f"a-{action}", actions=[payload])])
        assert kind == "v2"


def test_criteria_and_or_not_and_every_operator() -> None:
    rules = [
        _v2_rule(
            "ops",
            criteria={
                "all": [
                    {"field": "Stage", "op": "eq", "value": "Negotiation"},
                    {
                        "any": [
                            {"field": "Amount", "op": "gt", "value": 10},
                            {"field": "Amount", "op": "lt", "value": 0},
                            {"not": {"field": "Owner", "op": "is_empty"}},
                            {"field": "Lead_Source", "op": "neq", "value": "Cold"},
                            {"field": "Stage", "op": "in", "value": ["Negotiation"]},
                            {"field": "Stage", "op": "not_in", "value": ["Closed Won"]},
                            {"field": "Stage", "op": "changed_to", "value": "Negotiation"},
                            {"field": "Stage", "op": "changed_from", "value": "Proposal"},
                        ]
                    },
                ]
            },
        )
    ]
    kind, parsed = parse_ruleset(rules)
    assert kind == "v2"
    assert parsed.rules[0].criteria is not None


def test_validator_errors_name_rule_ids() -> None:
    with pytest.raises(ValueError, match="a-bad"):
        parse_ruleset([_v2_rule("a-good"), {"id": "a-bad", "event": {"type": "nope"}}])
    with pytest.raises(ValueError, match="dup"):
        parse_ruleset([_v2_rule("dup"), _v2_rule("dup")])
    with pytest.raises(ValueError, match="mixed"):
        parse_ruleset(
            [
                _v2_rule("v2-one"),
                {"id": "v1-one", "event": "deal_created", "action": "assign_owner"},
            ]
        )


def test_legacy_v1_still_accepted() -> None:
    kind, _ = parse_ruleset(
        [{"id": "owner", "event": "deal_created", "action": "assign_owner", "value": "team"}]
    )
    assert kind == "v1"
    analysis = analyze(
        WorkflowInput(
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
    )
    assert analysis.ready is True


def test_rule_schema_validates_v2_ruleset() -> None:
    schema = rule_schema()
    assert schema["title"] == "RulesetV2"
    assert "RuleV2" in schema["$defs"]


def test_simulator_trace_order_priority_then_id() -> None:
    rules = [
        {**_v2_rule("r-b"), "priority": 10},
        {**_v2_rule("r-a"), "priority": 10},
        {**_v2_rule("r-c"), "priority": 1},
    ]
    kind, parsed = parse_ruleset(rules)
    assert kind == "v2"
    result = simulate_v2(parsed, {"id": "d-1", "Stage": "New"})
    assert [step["rule"] for step in result["trace"]] == ["r-c", "r-a", "r-b"]
    assert [step["caused_by"] for step in result["trace"]] == ["e0", "e0", "e0"]
    assert result["external_actions"] == 0


def test_simulator_virtual_clock_and_fields_changed() -> None:
    rules = [
        {
            "id": "promote",
            "event": {"type": "record_created"},
            "priority": 1,
            "actions": [{"type": "field_update", "field": "Stage", "value": "Negotiation"}],
        },
        {
            "id": "followup",
            "event": {"type": "stage_changed", "field": "Stage"},
            "priority": 2,
            "criteria": {"field": "Stage", "op": "changed_to", "value": "Negotiation"},
            "actions": [{"type": "create_task", "value": "Follow up", "delay_days": 2}],
        },
    ]
    kind, parsed = parse_ruleset(rules)
    assert kind == "v2"
    result = simulate_v2(parsed, {"id": "d-2", "Stage": "Proposal"})
    assert result["state"]["Stage"] == "Negotiation"
    assert result["trace"][0]["fields_changed"] == ["Stage"]
    task_steps = [step for step in result["trace"] if step["action"] == "create_task"]
    assert len(task_steps) == 1
    assert task_steps[0]["day"] == 2
    assert result["days_elapsed"] == 2
    assert task_steps[0]["caused_by"] != "input"


def test_simulator_cycle_detection_and_step_limit() -> None:
    loop = [
        {
            "id": "ping",
            "event": {"type": "record_edited"},
            "actions": [{"type": "field_update", "field": "Stage", "value": "A"}],
        },
        {
            "id": "pong",
            "event": {"type": "record_edited"},
            "actions": [{"type": "field_update", "field": "Stage", "value": "B"}],
        },
    ]
    kind, parsed = parse_ruleset(loop)
    assert kind == "v2"
    result = simulate_v2(parsed, {"id": "d-3", "Stage": "New"}, initial_event="record_edited")
    assert [item["code"] for item in result["findings"]] == ["cycle_detected"]
    limited = simulate_v2(
        parsed, {"id": "d-3", "Stage": "New"}, initial_event="record_edited", max_steps=1
    )
    assert [item["code"] for item in limited["findings"]] == ["step_limit"]


def test_ledger_duplicate_detection() -> None:
    ledger = SideEffectLedger()
    assert ledger.record(record_id="d-1", action="send_email", template_or_url="t", day=0) is False
    assert ledger.record(record_id="d-1", action="send_email", template_or_url="t", day=0) is True
    assert ledger.record(record_id="d-1", action="send_email", template_or_url="t", day=1) is False
    assert len(ledger.duplicates()) == 1


def test_simulator_duplicate_side_effect_finding() -> None:
    rules = [
        {
            "id": "mail-a",
            "event": {"type": "record_created"},
            "priority": 1,
            "actions": [{"type": "send_email", "template": "owner-alert"}],
        },
        {
            "id": "mail-b",
            "event": {"type": "record_created"},
            "priority": 2,
            "actions": [{"type": "send_email", "template": "owner-alert"}],
        },
    ]
    analysis = analyze(WorkflowInput(rules=rules, record={"id": "d-9"}))
    assert analysis.ready is False
    assert [finding.code for finding in analysis.findings] == ["duplicate_side_effect"]
    assert analysis.legacy["external_actions"] == 0
    assert analysis.legacy["ledger"] and len(analysis.legacy["ledger"]) == 2


def test_v2_report_ids_unique_and_stable() -> None:
    payload = {
        "rules": [
            {
                "id": "mail-a",
                "event": {"type": "record_created"},
                "priority": 1,
                "actions": [{"type": "send_email", "template": "owner-alert"}],
            },
            {
                "id": "mail-b",
                "event": {"type": "record_created"},
                "priority": 2,
                "actions": [{"type": "send_email", "template": "owner-alert"}],
            },
        ],
        "record": {"id": "d-9"},
    }
    first = [finding.id for finding in analyze(WorkflowInput.model_validate(payload)).findings]
    second = [finding.id for finding in analyze(WorkflowInput.model_validate(payload)).findings]
    assert first == second
    assert len(set(first)) == len(first) == 1


@given(st.dictionaries(st.text(max_size=8), st.integers(), max_size=5))
def test_simulation_deterministic_hypothesis(extra: dict[str, int]) -> None:
    """Same input yields a byte-identical trace (TK-WF-F2 hypothesis)."""
    rules = [_v2_rule("h-a")]
    kind, parsed = parse_ruleset(rules)
    assert kind == "v2"
    record = {"id": "h-1", "Stage": "New", **{f"k-{k}": v for k, v in extra.items()}}
    first = canonical_json(simulate_v2(parsed, record))
    second = canonical_json(simulate_v2(parsed, record))
    assert first == second
