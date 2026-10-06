"""Intermediate rule language v2 (TK-WF-F1).

v2 rules describe CRM automation declaratively so the deterministic
simulator (:mod:`zohokit.modules.workflow.simulator`) and the static
linter (:mod:`zohokit.modules.workflow.analyzer`) share one schema:

- events: ``record_created``, ``record_edited``, ``field_changed``,
  ``stage_changed``, ``scheduled``, ``date_field_reached``
- criteria: ``all`` (AND) / ``any`` (OR) / ``not`` (NOT) over leaves
  with operators ``eq, neq, in, not_in, gt, lt, is_empty, changed_to,
  changed_from``
- actions: ``field_update``, ``assign_owner``, ``create_task``,
  ``send_email`` (simulated), ``webhook`` (simulated), ``function``
  (simulated, declared side effects)
- rule ``priority`` (lower fires first), ``execute_on``
  (``create|edit|both``) and ``repeat`` semantics

``send_email`` and ``webhook`` never leave the process: the simulator
records them in the side-effect ledger and reports
``external_actions: 0``. Legacy v1 rules (``{"id", "event": str,
"action": str}``) are still accepted by :func:`parse_ruleset` and run
through the unchanged legacy engine path.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

V2_EVENTS = (
    "record_created",
    "record_edited",
    "field_changed",
    "stage_changed",
    "scheduled",
    "date_field_reached",
)

V2_OPERATORS = (
    "eq",
    "neq",
    "in",
    "not_in",
    "gt",
    "lt",
    "is_empty",
    "changed_to",
    "changed_from",
)

V2_ACTIONS = (
    "field_update",
    "assign_owner",
    "create_task",
    "send_email",
    "webhook",
    "function",
)

#: Actions that only simulate an outside call (TK-WF-F3 ledger).
SIMULATED_ACTIONS = frozenset({"send_email", "webhook", "function"})

EventType = Literal[
    "record_created",
    "record_edited",
    "field_changed",
    "stage_changed",
    "scheduled",
    "date_field_reached",
]
Operator = Literal[
    "eq",
    "neq",
    "in",
    "not_in",
    "gt",
    "lt",
    "is_empty",
    "changed_to",
    "changed_from",
]
ActionType = Literal[
    "field_update",
    "assign_owner",
    "create_task",
    "send_email",
    "webhook",
    "function",
]
ExecuteOn = Literal["create", "edit", "both"]


class Event(BaseModel):
    """Trigger for one rule (TK-WF-F1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: EventType
    field: str | None = None
    offset_days: int | None = None

    @model_validator(mode="after")
    def _check_params(self) -> Event:
        if self.type in ("field_changed", "date_field_reached") and not self.field:
            raise ValueError(f"event {self.type!r} needs a field api_name")
        if self.type in ("scheduled", "date_field_reached") and self.offset_days is None:
            raise ValueError(f"event {self.type!r} needs offset_days")
        return self


class Criterion(BaseModel):
    """One AND/OR/NOT node or operator leaf (TK-WF-F1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    all: tuple[Criterion, ...] = ()
    any: tuple[Criterion, ...] = ()
    not_: Criterion | None = Field(default=None, alias="not")
    field: str | None = None
    op: Operator | None = None
    value: Any = None

    @model_validator(mode="after")
    def _check_shape(self) -> Criterion:
        branches = [
            bool(self.all),
            bool(self.any),
            self.not_ is not None,
            self.op is not None,
        ]
        if sum(branches) != 1:
            raise ValueError("criterion needs exactly one of all/any/not/leaf-op")
        if self.op is not None and not self.field:
            raise ValueError("criterion leaf needs a field api_name")
        return self


Criterion.model_rebuild()


class Action(BaseModel):
    """One rule action; external calls are simulated only (TK-WF-F1/F3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: ActionType
    field: str | None = None
    value: Any = None
    owner: str | None = None
    template: str | None = None
    url: str | None = None
    function_name: str | None = None
    side_effects: tuple[str, ...] = ()
    delay_days: int | None = None

    @model_validator(mode="after")
    def _check_params(self) -> Action:
        if self.type == "field_update" and not self.field:
            raise ValueError("field_update needs a field api_name")
        if self.type == "assign_owner" and not (isinstance(self.owner, str) and self.owner):
            raise ValueError("assign_owner needs an owner value")
        if self.type == "send_email" and not self.template:
            raise ValueError("send_email needs a template name")
        if self.type == "webhook" and not self.url:
            raise ValueError("webhook needs a url")
        if self.type == "function" and not self.function_name:
            raise ValueError("function needs a function_name")
        return self


class RuleV2(BaseModel):
    """One v2 automation rule (TK-WF-F1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    module: str = "Deals"
    event: Event
    execute_on: ExecuteOn = "both"
    priority: int = 100
    repeat: bool = True
    active: bool = True
    criteria: Criterion | None = None
    actions: tuple[Action, ...] = ()

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if not value:
            raise ValueError("rule id must be a non-empty string")
        return value


class RulesetV2(BaseModel):
    """A validated v2 rule set; errors name the offending rule IDs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rules: tuple[RuleV2, ...] = ()

    @model_validator(mode="after")
    def _check_unique_ids(self) -> RulesetV2:
        seen: set[str] = set()
        for rule in self.rules:
            if rule.id in seen:
                raise ValueError(f"duplicate rule id {rule.id!r}")
            seen.add(rule.id)
        return self


def _offenders(rules: list[Any], exc: Exception) -> str:
    """Name the v2 rules a validation error complains about (rule IDs)."""
    indexes: set[int] = set()
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            for error in errors():
                loc = error.get("loc", ()) if isinstance(error, dict) else ()
                steps = list(loc) if isinstance(loc, (tuple, list)) else []
                if len(steps) >= 2 and steps[0] == "rules" and isinstance(steps[1], int):
                    indexes.add(steps[1])
        except Exception:
            indexes = set()
    if not indexes:
        ids = [str(item.get("id", f"index-{n}")) for n, item in enumerate(rules)]
        return f"rule ids: {', '.join(ids)}"
    names = []
    for index in sorted(indexes):
        item = rules[index] if 0 <= index < len(rules) else None
        if isinstance(item, dict):
            names.append(str(item.get("id", f"index-{index}")))
        else:
            names.append(f"index-{index}")
    return f"rule ids: {', '.join(names)}"


def is_v2_rule(item: Any) -> bool:
    """Whether *item* uses the v2 shape (dict event/criteria/actions list)."""
    return (isinstance(item, dict) and isinstance(item.get("event"), dict)) or (
        isinstance(item, dict) and ("criteria" in item or "actions" in item)
    )


def parse_ruleset(rules: Any) -> tuple[Literal["v1", "v2"], Any]:
    """Parse *rules* as v2, else return them for the legacy v1 path.

    Returns ``("v2", RulesetV2)`` when every rule has the v2 shape and
    validates, otherwise ``("v1", rules)`` untouched for the legacy
    engine (which raises its own rule-ID-bearing errors). A mixed list
    raises ``ValueError`` naming the v1-shaped rule IDs.
    """
    if not isinstance(rules, list):
        raise ValueError("rules must be a list")
    if not rules:
        return ("v2", RulesetV2(rules=()))
    if all(is_v2_rule(item) for item in rules):
        try:
            return ("v2", RulesetV2.model_validate({"rules": rules}))
        except Exception as exc:
            raise ValueError(f"invalid v2 ruleset ({_offenders(rules, exc)}): {exc}") from None
    if not any(is_v2_rule(item) for item in rules):
        return ("v1", rules)
    offenders = sorted(
        str(item.get("id", f"index-{index}"))
        for index, item in enumerate(rules)
        if isinstance(item, dict) and not is_v2_rule(item)
    )
    raise ValueError(f"mixed v1/v2 rules; v1-shaped rule ids: {', '.join(offenders)}")


def rule_schema() -> dict[str, Any]:
    """JSON Schema for the v2 rule set (TK-WF-F1 acceptance)."""
    return RulesetV2.model_json_schema()


__all__: list[str] = [
    "SIMULATED_ACTIONS",
    "V2_ACTIONS",
    "V2_EVENTS",
    "V2_OPERATORS",
    "Action",
    "Criterion",
    "Event",
    "RuleV2",
    "RulesetV2",
    "is_v2_rule",
    "parse_ruleset",
    "rule_schema",
]
