"""Risk scoring per change: low, medium or high (TK-REL-5).

Documented scoring table (also in ``docs/modules/release.md``):

| Change | Risk |
|---|---|
| removal of any component | high |
| behavior kind added or changed | high |
| picklist value removed while records use it | high |
| field type change | high |
| layout-only change | low |
| anything else added or changed | medium |
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from zohokit.modules.release.diff import ComponentChange

RiskLevel = Literal["low", "medium", "high"]

#: Kinds whose add/change can alter automation behavior.
BEHAVIOR_KINDS: frozenset[str] = frozenset({"workflow", "validation", "function", "webhook"})

#: Kinds whose change is presentation without behavior.
LAYOUT_ONLY_KINDS: frozenset[str] = frozenset({"layout", "layout_rule", "custom_button", "role"})

_RISK_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class Risk:
    """One change scored with its reasons."""

    component_id: str
    level: RiskLevel
    reasons: tuple[str, ...]


def _in_use(attributes: dict[str, object]) -> bool:
    """Whether a removed picklist value is still referenced by records."""
    count = attributes.get("in_use_count", 0)
    if isinstance(count, bool):
        return count
    if isinstance(count, (int, float)) and count > 0:
        return True
    flag = attributes.get("in_use", False)
    return flag is True


def assess(
    change: ComponentChange,
    *,
    before_attributes: dict[str, object] | None = None,
) -> Risk:
    """Score one change; the highest applicable rule wins."""
    reasons: list[str] = []
    level: RiskLevel = "medium"
    if change.change == "removed":
        level = "high"
        reasons.append("removal")
    if change.kind in BEHAVIOR_KINDS and change.change in ("added", "changed"):
        level = "high"
        reasons.append(
            "behavior kind changed" if change.change == "changed" else "behavior kind added"
        )
    if (
        change.kind == "picklist_value"
        and change.change == "removed"
        and _in_use(before_attributes or {})
    ):
        reasons.append("picklist value removed while records use it")
    type_changed = any(entry.attribute == "data_type" for entry in change.attributes)
    if change.kind == "field" and change.change == "changed" and type_changed:
        level = "high"
        reasons.append("field type change")
    if not reasons:
        if change.kind in LAYOUT_ONLY_KINDS and change.change == "changed":
            level = "low"
            reasons.append("layout-only change")
        else:
            reasons.append("standard change")
    return Risk(component_id=change.component_id, level=level, reasons=tuple(reasons))


def release_risk(risks: list[Risk]) -> RiskLevel:
    """Overall release risk: the maximum per-change level."""
    level: RiskLevel = "low"
    for risk in risks:
        if _RISK_RANK[risk.level] > _RISK_RANK[level]:
            level = risk.level
    return level


__all__: list[str] = [
    "BEHAVIOR_KINDS",
    "LAYOUT_ONLY_KINDS",
    "Risk",
    "RiskLevel",
    "assess",
    "release_risk",
]
