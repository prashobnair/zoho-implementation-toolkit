"""Accepted-findings suppression file (``.zohokit-baseline.json``).

A baseline lists finding IDs a reviewer has accepted, each with a reason,
an approver and an expiry date. Active suppressions mark their findings as
``suppressed``: they stay visible in every report but no longer block
``ready``. Expired entries reactivate automatically; the caller passes the
current time explicitly so tests can freeze it.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from zohokit.core.findings import Report, Severity

BASELINE_VERSION = 1


class BaselineError(ValueError):
    """A baseline file is missing, unreadable, or fails validation."""


class BaselineEntry(BaseModel):
    """One accepted finding: stable ID plus review metadata."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[0-9a-f]{24}$")
    reason: str = Field(min_length=1)
    approver: str = Field(min_length=1)
    expires: date


class Baseline(BaseModel):
    """Versioned set of accepted findings."""

    model_config = ConfigDict(frozen=True)

    version: int = BASELINE_VERSION
    suppressions: list[BaselineEntry] = Field(default_factory=list)


def load_baseline(path: Path) -> Baseline:
    """Read and validate a baseline file; raise :class:`BaselineError`.

    A missing ``reason`` (or approver, or malformed ID/date) is a hard
    error: silent acceptances are never allowed. The message names the
    problem without echoing file contents.
    """
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BaselineError(f"cannot read baseline file: {exc.strerror or exc}") from exc
    except ValueError as exc:
        raise BaselineError(f"baseline file is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise BaselineError("baseline file must contain a JSON object")
    try:
        baseline = Baseline.model_validate(raw)
    except ValidationError as exc:
        raise BaselineError(_short_error(exc)) from exc
    if baseline.version != BASELINE_VERSION:
        raise BaselineError(f"unsupported baseline version {baseline.version}")
    return baseline


def _short_error(exc: ValidationError) -> str:
    """One line per problem, naming fields but never values."""
    parts = "; ".join(
        ".".join(str(step) for step in err["loc"]) + ": " + str(err["msg"]) for err in exc.errors()
    )
    return f"invalid baseline: {parts[:200]}"


def active_ids(baseline: Baseline, *, now: datetime) -> set[str]:
    """IDs whose suppression has not expired at ``now`` (date precision)."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    today = now.date()
    return {entry.id for entry in baseline.suppressions if entry.expires >= today}


def apply_baseline(report: Report, baseline: Baseline, *, now: datetime) -> Report:
    """Mark suppressed findings; recompute ``ready`` without them.

    Suppressed findings keep their severity and stay in ``findings`` (and
    in every renderer) with ``suppressed=True``. ``ready`` becomes true
    when no *unsuppressed* ``error`` or ``review`` finding remains; an
    already-ready report stays ready.
    """
    active = active_ids(baseline, now=now)
    if not active:
        return report
    findings = [
        finding if finding.id not in active else finding.model_copy(update={"suppressed": True})
        for finding in report.findings
    ]
    blocking = any(
        not item.suppressed and item.severity in (Severity.ERROR, Severity.REVIEW)
        for item in findings
    )
    return Report.build(
        module=report.module,
        run_id=report.run_id,
        started_at=report.started_at,
        finished_at=report.finished_at,
        findings=findings,
        ready=report.ready or not blocking,
        mode=report.mode,
        source=report.source,
        inputs_sha256=report.inputs_sha256,
        artifacts=dict(report.artifacts),
        side_effects=report.side_effects,
    )


__all__: list[str] = [
    "BASELINE_VERSION",
    "Baseline",
    "BaselineEntry",
    "BaselineError",
    "active_ids",
    "apply_baseline",
    "load_baseline",
]
