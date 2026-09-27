"""Module registry: the 8 ported modules (TK-MIG-3 lands in WP-08/09)."""

from __future__ import annotations

MODULES: tuple[str, ...] = (
    "migration",
    "release",
    "workflow",
    "forms",
    "books",
    "timeline",
    "metrics",
    "lead_routing",
)

__all__: list[str] = ["MODULES"]
