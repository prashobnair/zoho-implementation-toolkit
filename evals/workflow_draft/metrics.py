"""Workflow-draft eval metrics (AI-WF-1): field-level exact match, validity.

Dataset cases carry a natural-language description, module field
metadata and a gold v2 rule (null for should-abstain cases).
``case_variables`` renders the prompt variables exactly the way the
drafter does; ``validate_response`` enforces the structural guardrails
(language schema, field allowlist, action-target grounding against the
description, the confidence-0.6 abstention rule);
exact match scores semantic slots (event, execute_on, criteria leaves,
actions) ignoring naming slots (id, module, priority, repeat, active).
``bad_caught`` decides whether a bad recording was rejected, flagged
or fell back as its case expects.
"""

from __future__ import annotations

from typing import Any

from zohokit.ai.schemas import RuleDraft
from zohokit.core.ids import canonical_json
from zohokit.modules.workflow.draft import validate_draft

#: Confidence below which the drafter must abstain (AI-WF-1).
ABSTAIN_BELOW = 0.6

#: Rule slots ignored by exact match (naming, not semantics).
IGNORED_SLOTS = frozenset({"id", "module", "priority", "repeat", "active"})


def case_variables(case: dict[str, Any]) -> dict[str, str]:
    """Render deterministic prompt variables for a dataset case."""
    lines = [f"{name} ({dtype})" for name, dtype in sorted(case["input"]["fields"].items())]
    return {"description": case["input"]["description"], "field_list": "\n".join(lines)}


def _criteria_slots(node: Any) -> list[str]:
    if not isinstance(node, dict):
        return []
    slots = []
    for key in ("all", "any"):
        children = node.get(key, [])
        if isinstance(children, list):
            for child in children:
                slots.extend(_criteria_slots(child))
    inner = node.get("not")
    if isinstance(inner, dict):
        slots.extend(_criteria_slots(inner))
    if node.get("op"):
        slots.append(
            f"crit:{node.get('field')}:{node.get('op')}:{canonical_json(node.get('value'))}"
        )
    return slots


def rule_slots(rule: dict[str, Any]) -> list[str]:
    """Semantic slots of one v2 rule payload (naming slots excluded)."""
    if not isinstance(rule, dict) or not rule:
        return []
    slots = []
    event = rule.get("event", {})
    if isinstance(event, dict):
        slots.append(f"event:{event.get('type')}")
        if event.get("field"):
            slots.append(f"event-field:{event.get('field')}")
        if event.get("offset_days") is not None:
            slots.append(f"offset:{event.get('offset_days')}")
    if rule.get("execute_on"):
        slots.append(f"on:{rule.get('execute_on')}")
    slots.extend(_criteria_slots(rule.get("criteria")))
    for action in rule.get("actions", []) or []:
        if not isinstance(action, dict):
            continue
        detail = {
            key: action.get(key)
            for key in (
                "type",
                "field",
                "value",
                "owner",
                "template",
                "url",
                "function_name",
                "delay_days",
            )
            if action.get(key) not in (None, "")
        }
        slots.append(f"action:{canonical_json(detail)}")
    return sorted(slots)


def gold_rule(case: dict[str, Any]) -> dict[str, Any] | None:
    """Gold v2 rule payload (None means the case should abstain)."""
    rule = case["gold"].get("rule")
    return dict(rule) if isinstance(rule, dict) else None


def validate_response(case: dict[str, Any], draft: RuleDraft) -> list[str]:
    """Structural guardrails; value-free violation strings."""
    return validate_draft(
        set(case["input"]["fields"]),
        draft,
        description=case["input"]["description"],
        allow_targets=tuple(case["input"].get("allow_targets", ())),
    )


def case_scores(case: dict[str, Any], draft: RuleDraft) -> dict[str, int]:
    """Count matched/total semantic slots plus validity and abstention."""
    gold = gold_rule(case)
    if gold is None:
        abstain_total = 1
        abstain_correct = 1 if draft.abstain else 0
        valid = 1 if validate_response(case, draft) == [] else 0
        return {
            "slots_matched": 0,
            "slots_total": 0,
            "valid": valid,
            "total": 1,
            "abstain_correct": abstain_correct,
            "abstain_total": abstain_total,
        }
    want = rule_slots(gold)
    got = [] if draft.abstain else rule_slots(draft.rule)
    remaining = list(got)
    matched = 0
    for slot in want:
        if slot in remaining:
            remaining.remove(slot)
            matched += 1
    valid = 1 if validate_response(case, draft) == [] else 0
    return {
        "slots_matched": matched,
        "slots_total": len(want),
        "valid": valid,
        "total": 1,
        "abstain_correct": 0,
        "abstain_total": 0,
    }


def good_metrics(totals: dict[str, int]) -> dict[str, float]:
    """Aggregate gated quality metrics over the good split."""
    exact = totals["slots_matched"] / totals["slots_total"] if totals["slots_total"] else 1.0
    valid_rate = totals["valid"] / totals["total"] if totals["total"] else 1.0
    abstention = (
        totals["abstain_correct"] / totals["abstain_total"] if totals["abstain_total"] else 1.0
    )
    return {
        "field_exact_match": exact,
        "valid_rate": valid_rate,
        "abstention_rate": abstention,
    }


def case_exact(case: dict[str, Any], draft: RuleDraft) -> float:
    """Exact-match fraction of one response against gold (bad-set tripwire)."""
    scores = case_scores(case, draft)
    if not scores["slots_total"]:
        return 1.0 if draft.abstain else 0.0
    return scores["slots_matched"] / scores["slots_total"]


def bad_caught(case: dict[str, Any], ai_status: str, draft: RuleDraft | None) -> bool:
    """True when a bad recording met its expected safe outcome."""
    expected = case.get("expected", {}).get("outcome", "rejected")
    if expected == "fallback":
        return ai_status == "fallback"
    if ai_status == "fallback" or draft is None:
        return True
    if validate_response(case, draft):
        return True
    return case_exact(case, draft) < 0.5


__all__: list[str] = [
    "ABSTAIN_BELOW",
    "bad_caught",
    "case_exact",
    "case_scores",
    "case_variables",
    "gold_rule",
    "good_metrics",
    "rule_slots",
    "validate_response",
]
