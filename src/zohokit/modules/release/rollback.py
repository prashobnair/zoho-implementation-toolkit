"""Rollback plan artifact: the inverse of every change, signed (TK-REL-7).

The plan is proposal-only (STD-W1/W2): it lists the inverse action per
change with an idempotency key and a rollback note, hashed with the
canonical SHA-256 so a reviewer can verify exactly what was reviewed.
Data-losing inverses (field deletion, in-use picklist removal) are
flagged by the engine with an ``irreversible_change`` review finding;
the plan itself only describes, never executes.
"""

from __future__ import annotations

from zohokit.core.plan import Plan, PlannedCall
from zohokit.modules.release.diff import ComponentChange
from zohokit.modules.release.manifest import Component

#: Kinds whose removal destroys stored values (flagged, never auto-inverted).
DATA_LOSING_KINDS: frozenset[str] = frozenset({"field", "picklist_value"})


def is_data_losing(change: ComponentChange) -> bool:
    """Whether rolling back needs human review (removal of stored values)."""
    return change.change == "removed" and change.kind in DATA_LOSING_KINDS


def rollback_plan(changes: list[ComponentChange], before: dict[str, Component]) -> Plan:
    """Build the inverse-action plan for every change, in change order."""
    calls: list[PlannedCall] = []
    for change in changes:
        component_id = change.component_id
        if change.change == "added":
            digest = change.before_hash[:12] if change.before_hash else component_id
            calls.append(
                PlannedCall(
                    method="DELETE",
                    path=f"manifest/{component_id}",
                    body_redacted={},
                    idempotency_key=f"rollback-remove-{digest}",
                    depends_on=[],
                    rollback="Re-apply the promotion if the removal was wrong.",
                )
            )
        elif change.change == "removed":
            prior = before.get(component_id)
            attributes = dict(prior.attributes) if prior is not None else {}
            digest = change.before_hash[:12] if change.before_hash else component_id
            calls.append(
                PlannedCall(
                    method="CREATE",
                    path=f"manifest/{component_id}",
                    body_redacted=attributes,
                    idempotency_key=f"rollback-restore-{digest}",
                    depends_on=[],
                    rollback=(
                        "Data-losing inverse: confirm a backup exists before restoring. "
                        if is_data_losing(change)
                        else "Restore is additive; re-run the diff after restoring."
                    ),
                )
            )
        else:
            prior = before.get(component_id)
            attributes = dict(prior.attributes) if prior is not None else {}
            digest = change.after_hash[:12] if change.after_hash else component_id
            calls.append(
                PlannedCall(
                    method="UPDATE",
                    path=f"manifest/{component_id}",
                    body_redacted=attributes,
                    idempotency_key=f"rollback-revert-{digest}",
                    depends_on=[],
                    rollback="Re-apply the promotion if the revert was wrong.",
                )
            )
    return Plan(calls=calls)


def plan_note(component_count: int) -> str:
    """Human companion note for the rollback bundle (plan only, no writes)."""
    return (
        f"Rollback proposal for {component_count} change(s). "
        "This plan describes inverse actions for review; it performs no writes to Zoho. "
        "Verify the signed SHA-256 in plan.json before acting."
    )


__all__: list[str] = ["DATA_LOSING_KINDS", "is_data_losing", "plan_note", "rollback_plan"]
