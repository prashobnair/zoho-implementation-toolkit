"""Deterministic v2 rule simulator (TK-WF-F2).

An event queue with deterministic ordering, a virtual clock for
scheduled/date actions, per-step ``fields_changed``, state-signature
cycle detection, a step limit and a full causal trace (``caused_by``).
The same input always yields a byte-identical trace: queues sort by
``(day, seq)``, matching rules sort by ``(priority, rule id)`` and
signatures use canonical JSON. External calls only reach the
side-effect ledger; ``external_actions`` stays ``0``.
"""

from __future__ import annotations

import copy
from typing import Any

from zohokit.core.ids import canonical_json
from zohokit.modules.workflow.language import Action, Criterion, RulesetV2
from zohokit.modules.workflow.ledger import SideEffectLedger

_TIMER_EVENTS = frozenset({"scheduled", "date_field_reached"})
_EDIT_EVENTS = frozenset({"record_edited", "field_changed", "stage_changed"})


def _event_kind(event_type: str) -> str:
    if event_type == "record_created":
        return "create"
    if event_type in _EDIT_EVENTS:
        return "edit"
    return "any"


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def eval_criterion(
    node: Criterion | None,
    state: dict[str, Any],
    fields_changed: set[str],
    previous: dict[str, Any],
) -> bool:
    """Evaluate one criteria tree against *state* (pure, deterministic)."""
    if node is None:
        return True
    if node.all:
        return all(eval_criterion(child, state, fields_changed, previous) for child in node.all)
    if node.any:
        return any(eval_criterion(child, state, fields_changed, previous) for child in node.any)
    if node.not_ is not None:
        return not eval_criterion(node.not_, state, fields_changed, previous)
    field = node.field or ""
    current = state.get(field)
    if node.op == "eq":
        return bool(current == node.value)
    if node.op == "neq":
        return bool(current != node.value)
    if node.op == "in":
        return bool(current in (node.value if isinstance(node.value, list) else [node.value]))
    if node.op == "not_in":
        return bool(current not in (node.value if isinstance(node.value, list) else [node.value]))
    if node.op == "gt":
        left, right = _as_number(current), _as_number(node.value)
        return left is not None and right is not None and left > right
    if node.op == "lt":
        left, right = _as_number(current), _as_number(node.value)
        return left is not None and right is not None and left < right
    if node.op == "is_empty":
        return current is None or current == ""
    if node.op == "changed_to":
        return field in fields_changed and current == node.value
    if node.op == "changed_from":
        return field in fields_changed and previous.get(field) == node.value
    return False


def _matches(
    rule_event_type: str,
    rule_event_field: str | None,
    rule_execute_on: str,
    event: dict[str, Any],
) -> bool:
    if rule_event_type != event["type"]:
        return False
    if rule_event_field and event.get("field") != rule_event_field:
        return False
    kind = _event_kind(str(event["type"]))
    return rule_execute_on == "both" or kind == "any" or rule_execute_on == kind


def _action_target(action: Action) -> str:
    if action.type == "send_email":
        return str(action.template or "")
    if action.type == "webhook":
        return str(action.url or "")
    if action.type == "function":
        return str(action.function_name or "")
    if action.type == "create_task":
        return str(action.value if action.value is not None else "task")
    return ""


def simulate_v2(
    ruleset: RulesetV2,
    record: dict[str, Any],
    initial_event: str = "record_created",
    max_steps: int = 20,
) -> dict[str, Any]:
    """Run the v2 simulation; same input yields a byte-identical trace."""
    if not isinstance(record, dict):
        raise ValueError("record must be an object")
    if not isinstance(max_steps, int) or max_steps < 1:
        raise ValueError("max_steps must be positive")
    rules = sorted(ruleset.rules, key=lambda rule: (rule.priority, rule.id))
    by_id = {rule.id: rule for rule in rules}
    state: dict[str, Any] = copy.deepcopy(record)
    record_id = str(state.get("id", "record"))
    ledger = SideEffectLedger()
    trace: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    seq = 0

    def enqueue(
        event_type: str,
        *,
        day: int,
        caused_by: str,
        fields: list[str] | None = None,
        field: str | None = None,
        rule_id: str | None = None,
    ) -> None:
        nonlocal seq
        entry: dict[str, Any] = {
            "event_id": f"e{seq}",
            "type": event_type,
            "day": day,
            "caused_by": caused_by,
            "fields_changed": list(fields or []),
        }
        if field is not None:
            entry["field"] = field
        if rule_id is not None:
            entry["rule_id"] = rule_id
        seq += 1
        pending.append(entry)

    enqueue(initial_event, day=0, caused_by="input")
    for rule in rules:
        if rule.event.type in _TIMER_EVENTS:
            enqueue(
                rule.event.type,
                day=int(rule.event.offset_days or 0),
                caused_by="input",
                field=rule.event.field,
                rule_id=rule.id,
            )

    visited: set[str] = set()
    fired_once: set[str] = set()
    steps = 0
    step_no = 0
    day = 0
    last_day = 0
    while pending:
        pending.sort(key=lambda item: (int(item["day"]), str(item["event_id"])))
        event = pending.pop(0)
        day = int(event["day"])
        last_day = max(last_day, day)
        signature = canonical_json(
            {
                "day": day,
                "event": [
                    str(event["type"]),
                    str(event.get("field", "")),
                    sorted(str(name) for name in event.get("fields_changed", [])),
                ],
                "state": state,
            }
        )
        if signature in visited:
            findings.append({"code": "cycle_detected", "rule": str(event.get("rule_id", ""))})
            break
        visited.add(signature)
        changed = set(str(name) for name in event.get("fields_changed", []))
        candidates = rules
        if event.get("rule_id"):
            only = by_id.get(str(event["rule_id"]))
            candidates = [only] if only is not None else []
        for rule in candidates:
            if not rule.active:
                continue
            if not rule.repeat and rule.id in fired_once:
                continue
            if not _matches(rule.event.type, rule.event.field, rule.execute_on, event):
                continue
            previous = copy.deepcopy(state)
            if not eval_criterion(rule.criteria, state, changed, previous):
                continue
            fired_once.add(rule.id)
            for action in rule.actions:
                steps += 1
                if steps > max_steps:
                    findings.append({"code": "step_limit", "rule": rule.id})
                    pending.clear()
                    break
                step_no += 1
                step_id = f"s{step_no}"
                before = copy.deepcopy(state)
                action_day = day + int(action.delay_days or 0)
                last_day = max(last_day, action_day)
                if action.type in ("field_update", "assign_owner"):
                    if action.type == "field_update":
                        state[str(action.field)] = copy.deepcopy(action.value)
                        written = [str(action.field)]
                    else:
                        state["Owner"] = action.owner
                        written = ["Owner"]
                    changed_now = sorted(
                        key
                        for key in written
                        if before.get(key) != state.get(key) or key not in before
                    )
                    trace.append(
                        {
                            "step": step_id,
                            "rule": rule.id,
                            "action": action.type,
                            "day": action_day,
                            "caused_by": str(event["event_id"]),
                            "fields_changed": changed_now,
                            "detail": {"field": written[0]},
                        }
                    )
                    if changed_now:
                        enqueue(
                            "record_edited",
                            day=action_day,
                            caused_by=step_id,
                            fields=changed_now,
                        )
                        for name in changed_now:
                            enqueue(
                                "field_changed",
                                day=action_day,
                                caused_by=step_id,
                                fields=[name],
                                field=name,
                            )
                        if "Stage" in changed_now:
                            enqueue(
                                "stage_changed",
                                day=action_day,
                                caused_by=step_id,
                                fields=["Stage"],
                                field="Stage",
                            )
                else:
                    target = _action_target(action)
                    duplicate = ledger.record(
                        record_id=record_id,
                        action=action.type,
                        template_or_url=target,
                        day=action_day,
                        rule_id=rule.id,
                    )
                    trace.append(
                        {
                            "step": step_id,
                            "rule": rule.id,
                            "action": action.type,
                            "day": action_day,
                            "caused_by": str(event["event_id"]),
                            "fields_changed": [],
                            "detail": {"target": target, "duplicate": duplicate},
                        }
                    )
                    if duplicate:
                        findings.append(
                            {
                                "code": "duplicate_side_effect",
                                "rule": rule.id,
                                "action": action.type,
                                "target": target,
                                "day": action_day,
                            }
                        )
            if not pending and steps > max_steps:
                break
    return {
        "mode": "simulation_only",
        "language": "v2",
        "state": state,
        "trace": trace,
        "findings": findings,
        "ledger": list(ledger.entries),
        "external_actions": 0,
        "days_elapsed": last_day,
    }


__all__: list[str] = ["eval_criterion", "simulate_v2"]
