"""Activity/history preservation check (TK-MIG-F8).

Entities carrying a ``history`` mapping section declare which activity
types the target can hold. Rows with any other type yield
``history_type_unsupported`` warnings (the import plan must carry them
another way), plus one info finding per entity with per-parent counts.
"""

from __future__ import annotations

from zohokit.core.findings import Finding, Severity
from zohokit.modules.migration.mapping import EntityMapping


def parent_column(entity: EntityMapping, header: list[str]) -> str | None:
    """Source column linking history rows to their parent, if resolvable."""
    for lookup in entity.lookups.values():
        if lookup.via in header:
            return lookup.via
    return None


def check_history(
    entity: EntityMapping,
    rows: list[tuple[str, dict[str, str]]],
    header: list[str],
) -> list[Finding]:
    """Flag unsupported history types and summarize counts per parent."""
    config = entity.history
    if config is None or config.type_col not in header:
        return []
    supported = set(config.supported)
    counts: dict[str, int] = {}
    parent_col = parent_column(entity, header)
    findings: list[Finding] = []
    for key, row in rows:
        if parent_col is not None:
            parent = (row.get(parent_col) or "").strip() or "unlinked"
            counts[parent] = counts.get(parent, 0) + 1
        history_type = (row.get(config.type_col) or "").strip()
        if history_type and history_type not in supported:
            findings.append(
                Finding.create(
                    module="migration",
                    code="history_type_unsupported",
                    severity=Severity.WARNING,
                    entity=entity.name,
                    entity_id=key,
                    message="History type has no target module to hold it.",
                    evidence={
                        "history_type": history_type,
                        "type_column": config.type_col,
                        "supported_count": len(supported),
                    },
                    remediation="Carry this history outside the import (notes or files).",
                    discriminator=f"history\0{history_type}",
                )
            )
    findings.append(
        Finding.create(
            module="migration",
            code="history_type_unsupported",
            severity=Severity.INFO,
            entity=entity.name,
            entity_id="counts",
            message=f"History counts across {len(counts)} parent(s).",
            evidence={"counts": counts, "total": sum(counts.values())},
            remediation="Verify every parent lands with its history after import.",
            discriminator="history\0counts",
        )
    )
    return findings


__all__: list[str] = ["check_history", "parent_column"]
