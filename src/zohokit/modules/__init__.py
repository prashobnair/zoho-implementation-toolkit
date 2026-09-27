"""Module registry and the shared analysis container (TK-MIG-3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from zohokit.core.findings import Finding

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


@dataclass(frozen=True)
class Analysis:
    """One engine run: new-style findings plus the legacy result dict.

    ``legacy`` is the verbatim port output that ``report.to_legacy_dict()``
    reproduces for WP-06 golden parity; ``ready`` mirrors the legacy
    readiness flag.
    """

    findings: tuple[Finding, ...] = ()
    legacy: dict[str, Any] = field(default_factory=dict)
    ready: bool = False


__all__: list[str] = ["MODULES", "Analysis"]
