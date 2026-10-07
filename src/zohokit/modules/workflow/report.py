"""Workflow report: new envelope plus the legacy reproduction (TK-MIG-3)."""

from __future__ import annotations

import copy
from typing import Any

from zohokit.core.context import RunContext
from zohokit.core.findings import Report
from zohokit.modules import Analysis


def _simulation_block(legacy: dict[str, Any]) -> dict[str, Any] | None:
    """Reachable causal trace for one v2 run (TK-WF-F2).

    Legacy v1 runs carry no block: their trace stays in the parity
    reproduction only.
    """
    if legacy.get("language") != "v2":
        return None
    steps = []
    for step in legacy.get("trace", []) or []:
        if not isinstance(step, dict):
            continue
        steps.append(
            {
                "step": step.get("step"),
                "rule": step.get("rule"),
                "action": step.get("action"),
                "day": step.get("day"),
                "caused_by": step.get("caused_by"),
                "fields_changed": list(step.get("fields_changed", []) or []),
            }
        )
    return {
        "trace": steps,
        "ledger": list(legacy.get("ledger", []) or []),
        "external_actions": int(legacy.get("external_actions", 0)),
        "days_elapsed": int(legacy.get("days_elapsed", 0)),
    }


def build_report(analysis: Analysis, *, ctx: RunContext, inputs_sha256: str) -> Report:
    """Build the versioned envelope; the frozen clock keeps runs identical."""
    return Report.build(
        module="workflow",
        run_id=inputs_sha256,
        started_at=ctx.now,
        finished_at=ctx.now,
        findings=list(analysis.findings),
        ready=analysis.ready,
        mode=ctx.mode,
        inputs_sha256=inputs_sha256,
        simulation=_simulation_block(analysis.legacy),
    )


def to_legacy_dict(analysis: Analysis) -> dict[str, Any]:
    """Reproduce the legacy simulation dict for legacy parity-golden comparison."""
    return copy.deepcopy(analysis.legacy)


__all__: list[str] = ["build_report", "to_legacy_dict"]
