"""Workflow static lint + real-rule import (UC-WF-1/3, TK-WF-F4)."""

from __future__ import annotations

import json
from pathlib import Path

from zohokit.modules.workflow.analyzer import lint
from zohokit.modules.workflow.import_real import ActionMaps, translate_ruleset
from zohokit.modules.workflow.language import RulesetV2, parse_ruleset

ROOT = Path(__file__).resolve().parent.parent.parent.parent
CASSETTES = ROOT / "tests" / "contract" / "cassettes"
FIELDS_DEALS = ROOT / "cassettes" / "crm" / "fields_Deals.json"


def _body(name: str) -> dict[str, object]:
    envelope = json.loads((CASSETTES / name).read_text(encoding="utf-8"))
    body = envelope["response"]["body"]
    assert isinstance(body, dict)
    return body


def _deals_fields() -> set[str]:
    body = json.loads(FIELDS_DEALS.read_text(encoding="utf-8"))["response"]["body"]
    return {str(item["api_name"]) for item in body["fields"]}


def _maps() -> ActionMaps:
    body = _body("crm_workflow_seeded_actions.json")
    return ActionMaps(
        field_updates={
            str(item["id"]): {
                "field": str(item["field"]["api_name"]),
                "value": (item.get("value") or [None])[0],
            }
            for item in body["field_updates"]
        }
    )


def _seeded_ruleset() -> RulesetV2:
    payload = _body("crm_workflow_seeded.json")
    assert sorted(payload) == ["info", "workflow_rules"]
    ruleset, unsupported = translate_ruleset(payload, maps=_maps())
    assert unsupported == []
    assert len(ruleset.rules) == 6
    return ruleset


def test_seeded_set_finds_exactly_four_issues() -> None:
    """The 4 seeded dev-org issues, and nothing else (TK-WF-F4 acceptance)."""
    findings = lint(_seeded_ruleset(), metadata={"Deals": _deals_fields()})
    assert sorted(finding.code for finding in findings) == [
        "conflicting_field_updates",
        "empty_rule",
        "potential_loop",
        "stale_field_reference",
    ]
    by_code = {finding.code: finding for finding in findings}
    assert by_code["potential_loop"].entity_id == "5550000000011000011"
    assert by_code["potential_loop"].evidence["path"] == [
        "5550000000011000011",
        "5550000000011000012",
        "5550000000011000011",
    ]
    assert by_code["conflicting_field_updates"].entity_id == "Deals.Stage"
    assert by_code["stale_field_reference"].entity_id == "Deals.Ghost_Field__s"
    assert by_code["empty_rule"].entity_id == "5550000000011000041"
    ids = [finding.id for finding in findings]
    assert len(set(ids)) == len(ids) == 4


def test_seeded_ids_stable_across_runs() -> None:
    metadata = {"Deals": _deals_fields()}
    first = [finding.id for finding in lint(_seeded_ruleset(), metadata=metadata)]
    second = [finding.id for finding in lint(_seeded_ruleset(), metadata=metadata)]
    assert first == second


def test_dead_webhook_limit_unsupported() -> None:
    kind, parsed = parse_ruleset(
        [
            {
                "id": "off",
                "event": {"type": "record_created"},
                "active": False,
                "actions": [{"type": "assign_owner", "owner": "x"}],
            },
            {
                "id": "hook",
                "event": {"type": "record_created"},
                "actions": [{"type": "webhook", "url": "https://example.invalid/h"}],
            },
            {
                "id": "busy",
                "event": {"type": "record_created"},
                "actions": [
                    {"type": "send_email", "template": "t"},
                    {"type": "send_email", "template": "u"},
                ],
            },
        ]
    )
    assert kind == "v2"
    assert isinstance(parsed, RulesetV2)
    findings = lint(
        parsed,
        webhook_failures={"https://example.invalid/h": "timeout"},
        limits={"Deals": {"send_email": 2}},
    )
    assert sorted(finding.code for finding in findings) == [
        "dead_rule",
        "near_limit",
        "webhook_failing",
    ]


def test_unsupported_constructs_listed_never_approximated() -> None:
    payload = {
        "workflow_rules": [
            {
                "id": "5550000000011000091",
                "module": {"api_name": "Deals"},
                "execute_when": {"type": "delete", "details": {}},
                "status": {"active": True},
                "conditions": [
                    {
                        "sequence_number": 1,
                        "criteria_details": {
                            "criteria": {
                                "group_operator": "OR",
                                "group": [
                                    {
                                        "comparator": "contains",
                                        "field": {"api_name": "Deal_Name"},
                                        "type": "value",
                                        "value": "x",
                                    }
                                ],
                            }
                        },
                        "instant_actions": {
                            "actions": [{"id": "t1", "name": "Tag", "type": "add_tags"}]
                        },
                        "scheduled_actions": [],
                    }
                ],
            }
        ]
    }
    ruleset, unsupported = translate_ruleset(payload, maps=ActionMaps())
    assert len(ruleset.rules) == 0
    assert [item.construct for item in unsupported] == ["trigger-type:delete"]
    findings = lint(ruleset, unsupported=unsupported)
    assert [finding.code for finding in findings] == ["unsupported_construct"]
    assert findings[0].entity_id == "5550000000011000091"


def test_stale_uses_real_deals_metadata() -> None:
    assert "Stage" in _deals_fields()
    assert "Ghost_Field__s" not in _deals_fields()
