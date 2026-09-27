"""Unit tests for dry-run plans (STD-W1/W2 scaffold)."""

from __future__ import annotations

from zohokit.core.plan import Plan, PlannedCall


def _plan() -> Plan:
    return Plan(
        calls=[
            PlannedCall(
                method="POST",
                path="/crm/v8/Contacts",
                body_redacted={"email": "a***@example.invalid"},
                idempotency_key="csv:contacts:1",
                depends_on=[],
                rollback="Delete created contacts listed in the target-ID ledger.",
            )
        ]
    )


def test_plan_round_trip_json() -> None:
    plan = _plan()
    assert Plan.model_validate_json(plan.model_dump_json()) == plan


def test_plan_hash_is_stable() -> None:
    assert _plan().canonical_hash() == _plan().canonical_hash()
