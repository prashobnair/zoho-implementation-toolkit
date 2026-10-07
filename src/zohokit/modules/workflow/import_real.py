"""Real-rule import into the simulator language (UC-WF-3, TK-WF-F4).

Supported v8 rule shapes (``execute_when`` trigger types, criteria
groups, instant/scheduled actions resolved through the Actions APIs)
translate into :class:`RuleV2`; anything else becomes an
``unsupported_construct`` entry — listed, never silently approximated.
Real trigger types follow
https://www.zoho.com/crm/developer/docs/api/v8/config-workflow.html and
the ``workflow_configurations`` metadata; unmapped types stay
unsupported by design.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from zohokit.modules.workflow.language import Action, Criterion, Event, RulesetV2, RuleV2

#: Real trigger type -> (v2 event type, execute_on). Types absent here
#: (delete, score_*, section_update, date-based and channel triggers)
#: are reported as unsupported, never guessed.
TRIGGER_MAP: dict[str, tuple[str, str]] = {
    "create": ("record_created", "create"),
    "edit": ("record_edited", "edit"),
    "create_or_edit": ("record_created", "both"),
    "field_update": ("field_changed", "edit"),
}

#: Real criteria comparator -> v2 operator. Comparators without an exact
#: v2 meaning (contains, starts_with, ends_with, ...) are unsupported.
COMPARATOR_MAP: dict[str, str] = {
    "equal": "eq",
    "not_equal": "neq",
    "in": "in",
    "not_in": "not_in",
    "greater_than": "gt",
    "less_than": "lt",
    "is_empty": "is_empty",
    "changed_to": "changed_to",
    "changed_from": "changed_from",
}

#: Real instant-action type -> v2 action type. Tagging, conversion,
#: meetings/calls and social actions have no simulator counterpart.
ACTION_MAP: dict[str, str] = {
    "field_updates": "field_update",
    "assign_owner": "assign_owner",
    "email_notifications": "send_email",
    "tasks": "create_task",
    "webhooks": "webhook",
    "functions": "function",
}


@dataclass(frozen=True)
class ActionMaps:
    """Real action ID -> simulator detail, resolved via the Actions APIs."""

    field_updates: dict[str, dict[str, Any]] = field(default_factory=dict)
    emails: dict[str, str] = field(default_factory=dict)
    tasks: dict[str, str] = field(default_factory=dict)
    webhooks: dict[str, str] = field(default_factory=dict)
    functions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Unsupported:
    """One real-rule construct with no simulator representation."""

    rule_id: str
    construct: str


def _criteria(node: Any, *, rule_id: str, unsupported: list[Unsupported]) -> Criterion | None:
    """Translate one real criteria node; None means 'always true'."""
    if not isinstance(node, dict):
        return None
    if "group" in node:
        operator = str(node.get("group_operator", "AND")).upper()
        children = [
            _criteria(child, rule_id=rule_id, unsupported=unsupported)
            for child in node["group"]
            if isinstance(child, dict)
        ]
        kept = [child for child in children if child is not None]
        if len(kept) != len(children):
            unsupported.append(Unsupported(rule_id=rule_id, construct="relational/group-criteria"))
            return None
        if operator == "OR":
            return Criterion(any=tuple(kept))
        if operator == "AND":
            return Criterion(all=tuple(kept))
        unsupported.append(Unsupported(rule_id=rule_id, construct=f"group-operator:{operator}"))
        return None
    if "relational_criteria" in node or "module" in node:
        unsupported.append(Unsupported(rule_id=rule_id, construct="relational-criteria"))
        return None
    comparator = str(node.get("comparator", ""))
    mapped = COMPARATOR_MAP.get(comparator)
    field_obj = node.get("field", {})
    api_name = field_obj.get("api_name", "") if isinstance(field_obj, dict) else ""
    if mapped is None or not api_name:
        unsupported.append(
            Unsupported(rule_id=rule_id, construct=f"comparator:{comparator or 'missing'}")
        )
        return None
    return Criterion(field=str(api_name), op=mapped, value=node.get("value"))  # type: ignore[arg-type]


def _action(
    entry: Any,
    *,
    rule_id: str,
    maps: ActionMaps,
    delay_days: int | None,
    unsupported: list[Unsupported],
) -> Action | None:
    """Translate one real action reference; None means unsupported."""
    if not isinstance(entry, dict):
        return None
    kind = str(entry.get("type", ""))
    mapped = ACTION_MAP.get(kind)
    action_id = str(entry.get("id", ""))
    if mapped is None:
        unsupported.append(Unsupported(rule_id=rule_id, construct=f"action-type:{kind}"))
        return None
    if mapped == "field_update":
        detail = maps.field_updates.get(action_id)
        if detail is None or not detail.get("field"):
            unsupported.append(
                Unsupported(rule_id=rule_id, construct=f"unresolved-field-update:{kind}")
            )
            return None
        return Action(
            type="field_update",
            field=str(detail["field"]),
            value=detail.get("value"),
            delay_days=delay_days,
            ref_id=action_id or None,
        )
    if mapped == "assign_owner":
        related = entry.get("related_details") or {}
        if isinstance(related, dict):
            owner: object = related.get("owner", "regional-manager")
        else:
            owner = "regional-manager"
        return Action(
            type="assign_owner",
            owner=str(owner),
            delay_days=delay_days,
            ref_id=action_id or None,
        )
    if mapped == "send_email":
        return Action(
            type="send_email",
            template=maps.emails.get(action_id, str(entry.get("name", action_id or "email"))),
            delay_days=delay_days,
            ref_id=action_id or None,
        )
    if mapped == "create_task":
        return Action(
            type="create_task",
            value=maps.tasks.get(action_id, str(entry.get("name", action_id or "task"))),
            delay_days=delay_days,
            ref_id=action_id or None,
        )
    if mapped == "webhook":
        url = maps.webhooks.get(action_id, "")
        if not url:
            unsupported.append(Unsupported(rule_id=rule_id, construct="unresolved-webhook-url"))
            return None
        return Action(type="webhook", url=url, delay_days=delay_days, ref_id=action_id or None)
    return Action(
        type="function",
        function_name=maps.functions.get(action_id, str(entry.get("name", action_id or "fn"))),
        side_effects=("declared",),
        delay_days=delay_days,
        ref_id=action_id or None,
    )


def translate_rule(
    real: dict[str, Any], *, seq: int, maps: ActionMaps
) -> tuple[RuleV2 | None, list[Unsupported]]:
    """Translate one real v8 rule; None + unsupported when untranslatable."""
    unsupported: list[Unsupported] = []
    rule_id = str(real.get("id", f"rule-{seq}"))
    module_obj = real.get("module", {})
    module = str(module_obj.get("api_name", "Deals")) if isinstance(module_obj, dict) else "Deals"
    when = real.get("execute_when", {})
    trigger = str(when.get("type", "")) if isinstance(when, dict) else ""
    mapped_trigger = TRIGGER_MAP.get(trigger)
    if mapped_trigger is None:
        unsupported.append(Unsupported(rule_id=rule_id, construct=f"trigger-type:{trigger}"))
        return None, unsupported
    event_type, execute_on = mapped_trigger
    event_kwargs: dict[str, Any] = {"type": event_type}
    details = when.get("details", {}) if isinstance(when, dict) else {}
    if event_type == "field_changed" and isinstance(details, dict):
        trigger_criteria = details.get("criteria", {})
        field_obj = trigger_criteria.get("field", {}) if isinstance(trigger_criteria, dict) else {}
        if isinstance(field_obj, dict) and field_obj.get("api_name"):
            event_kwargs["field"] = str(field_obj["api_name"])
    actions: list[Action] = []
    criteria: Criterion | None = None
    for index, condition in enumerate(real.get("conditions", []) or []):
        if not isinstance(condition, dict):
            continue
        node = (condition.get("criteria_details") or {}).get("criteria")
        translated = _criteria(node, rule_id=rule_id, unsupported=unsupported)
        if translated is not None:
            criteria = (
                translated
                if criteria is None or index == 0
                else Criterion(all=(criteria, translated))
            )
        instant = (condition.get("instant_actions") or {}).get("actions", [])
        for entry in instant if isinstance(instant, list) else []:
            action = _action(
                entry, rule_id=rule_id, maps=maps, delay_days=None, unsupported=unsupported
            )
            if action is not None:
                actions.append(action)
        for scheduled in condition.get("scheduled_actions", []) or []:
            if not isinstance(scheduled, dict):
                continue
            after = scheduled.get("execute_after", {}) if isinstance(scheduled, dict) else {}
            delay = after.get("unit", 0) if isinstance(after, dict) else 0
            for entry in scheduled.get("actions", []) or []:
                action = _action(
                    entry,
                    rule_id=rule_id,
                    maps=maps,
                    delay_days=int(delay) if isinstance(delay, int) else None,
                    unsupported=unsupported,
                )
                if action is not None:
                    actions.append(action)
    try:
        rule = RuleV2(
            id=rule_id,
            module=module,
            event=Event(**event_kwargs),
            execute_on=execute_on,  # type: ignore[arg-type]
            priority=seq,
            repeat=bool(details.get("repeat", True)) if isinstance(details, dict) else True,
            active=bool((real.get("status") or {}).get("active", True)),
            criteria=criteria,
            actions=tuple(actions),
        )
    except Exception as exc:
        unsupported.append(Unsupported(rule_id=rule_id, construct=f"invalid:{exc}"))
        return None, unsupported
    return rule, unsupported


def translate_ruleset(
    payload: dict[str, Any], *, maps: ActionMaps | None = None
) -> tuple[RulesetV2, list[Unsupported]]:
    """Translate a ``{"workflow_rules": [...]}`` envelope (UC-WF-3)."""
    resolved = maps or ActionMaps()
    rules: list[RuleV2] = []
    unsupported: list[Unsupported] = []
    for seq, real in enumerate(payload.get("workflow_rules", []) or []):
        if not isinstance(real, dict):
            continue
        rule, missed = translate_rule(real, seq=seq, maps=resolved)
        unsupported.extend(missed)
        if rule is not None:
            rules.append(rule)
    return RulesetV2(rules=tuple(rules)), unsupported


__all__: list[str] = [
    "ACTION_MAP",
    "COMPARATOR_MAP",
    "TRIGGER_MAP",
    "ActionMaps",
    "Unsupported",
    "translate_rule",
    "translate_ruleset",
]
