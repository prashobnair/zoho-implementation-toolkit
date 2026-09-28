"""Books report: new envelope plus the legacy reproduction (TK-MIG-3)."""

from __future__ import annotations

import copy
from typing import Any

from zohokit.core.context import RunContext
from zohokit.core.findings import Report
from zohokit.modules import Analysis


def build_report(analysis: Analysis, *, ctx: RunContext, inputs_sha256: str) -> Report:
    """Build the versioned envelope; the frozen clock keeps runs identical."""
    return Report.build(
        module="books",
        run_id=inputs_sha256,
        started_at=ctx.now,
        finished_at=ctx.now,
        findings=list(analysis.findings),
        ready=analysis.ready,
        mode=ctx.mode,
        inputs_sha256=inputs_sha256,
    )


def to_legacy_dict(analysis: Analysis) -> dict[str, Any]:
    """Reproduce the legacy reconciliation dict for legacy parity-golden comparison."""
    return copy.deepcopy(analysis.legacy)


__all__: list[str] = ["build_report", "to_legacy_dict"]
