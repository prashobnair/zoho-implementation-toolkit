"""Signed import plan artifact (TK-MIG-F9, STD-W1/W2).

Batches stream in dependency order (Accounts → Contacts → Deals →
Activities/Notes) with idempotency keys (``source_system:source_id``),
estimated API calls, a recommended External ID field, and a rollback
note explaining why rollback needs a target-ID ledger captured at
import time (source IDs alone cannot drive it). The plan hash signs the
canonical JSON so review can verify exactness. Nothing here writes to
Zoho: the plan is the proposal.
"""

from __future__ import annotations

import math
from pathlib import Path

from zohokit.core.plan import Plan, PlannedCall, write_bundle
from zohokit.modules.migration.mapping import MappingDoc

#: Records per batch call (documented import-batch assumption).
BATCH_SIZE = 100


#: Dependency ranks by target module (lower imports first; ties by module name).
def module_rank(target_module: str, entity_name: str) -> tuple[int, str]:
    """Rank import order: Accounts → Contacts → Deals → history, then rest."""
    folded = target_module.casefold()
    name = entity_name.casefold()
    if "account" in folded:
        rank = 0
    elif folded in ("contacts", "leads") or "contact" in folded or "lead" in folded:
        rank = 1
    elif "deal" in folded or "potential" in folded:
        rank = 2
    elif (
        "activit" in folded
        or folded in ("calls", "tasks", "meetings", "notes")
        or name in ("activities", "notes", "calls", "tasks", "meetings")
    ):
        rank = 3
    else:
        rank = 4
    return (rank, target_module.casefold())


def external_id_field(doc_entity: object, fallback: str = "External_ID__s") -> str:
    """Recommended External ID field: the mapped one, else the default name."""
    external = getattr(doc_entity, "external_id", None)
    field = getattr(external, "field", None)
    return str(field) if field else fallback


def build_plan(
    doc: MappingDoc,
    counts: dict[str, int],
    *,
    source_system: str | None = None,
) -> Plan:
    """Build the ordered, hash-stable import plan for *counts* per entity.

    One ``PlannedCall`` per batch (POST ``/crm/v8/{module}``): batches of
    a module chain on the previous batch, and the first batch of a module
    on the last batch of its parent rank. Estimated API calls equal the
    batch count (one bulk call per 100 records).
    """
    system = source_system or doc.source
    ordered = sorted(doc.entities, key=lambda e: module_rank(e.target_module, e.name))
    calls: list[PlannedCall] = []
    parent_tail: str | None = None
    for entity in ordered:
        total = counts.get(entity.name, 0)
        batches = max(math.ceil(total / BATCH_SIZE), 1) if total else 0
        external_field = external_id_field(entity)
        previous: str | None = parent_tail
        for batch in range(1, batches + 1):
            key = f"{system}:{entity.target_module}:batch-{batch}"
            depends = [previous] if previous is not None else []
            calls.append(
                PlannedCall(
                    method="POST",
                    path=f"/crm/v8/{entity.target_module}",
                    body_redacted={
                        "batch": f"{batch}/{batches}",
                        "records": min(BATCH_SIZE, total - (batch - 1) * BATCH_SIZE),
                        "external_id_field": external_field,
                        "idempotency_key_pattern": f"{system}:<source_id>",
                    },
                    idempotency_key=key,
                    depends_on=depends,
                    rollback=(
                        f"Delete the batch records using the target-ID ledger for {key} "
                        "(reverse dependency order)."
                    ),
                )
            )
            previous = key
        if batches:
            parent_tail = previous
    return Plan(calls=calls)


def estimated_api_calls(plan: Plan) -> int:
    """One API call per planned batch (bulk import assumption)."""
    return len(plan.calls)


ROLLBACK_NOTE = (
    "Rollback needs a target-ID ledger captured at import time: for every "
    "idempotency key (source_system:source_id), record the created Zoho "
    "record ID when the batch succeeds. Source IDs alone cannot drive "
    "rollback, because the target assigns its own IDs on create. To roll "
    "back, delete ledger IDs in reverse dependency order "
    "(Activities/Notes → Deals → Contacts → Accounts) after a reviewed export."
)


def plan_note(doc: MappingDoc, counts: dict[str, int], plan: Plan) -> str:
    """Human-readable plan companion: order, batches, calls, ledger note."""
    lines = [
        "# Migration import plan (read-only proposal)",
        "",
        f"Source system: `{doc.source}`",
        f"Estimated API calls: {estimated_api_calls(plan)}",
        "",
        "## Batches (dependency order)",
        "",
    ]
    for entity in sorted(doc.entities, key=lambda e: module_rank(e.target_module, e.name)):
        external = external_id_field(entity)
        lines.append(
            f"- `{entity.target_module}` ({entity.name}): "
            f"{counts.get(entity.name, 0)} rows, "
            f"external ID `{external}`"
        )
    lines += ["", "## Rollback", "", ROLLBACK_NOTE, ""]
    return "\n".join(lines)


def write_plan(
    doc: MappingDoc,
    counts: dict[str, int],
    directory: str | Path,
    *,
    source_system: str | None = None,
) -> tuple[Path, Path, Plan]:
    """Build the plan, write ``plan.json`` + ``plan.md``, return paths + plan."""
    plan = build_plan(doc, counts, source_system=source_system)
    json_path, _ = write_bundle(plan, Path(directory), note="")
    md_path = Path(directory) / "plan.md"
    md_path.write_text(plan_note(doc, counts, plan), encoding="utf-8")
    return json_path, md_path, plan


__all__: list[str] = [
    "BATCH_SIZE",
    "ROLLBACK_NOTE",
    "Plan",
    "build_plan",
    "estimated_api_calls",
    "external_id_field",
    "module_rank",
    "plan_note",
    "write_plan",
]
