"""Finding and Report models per STD §3.5.

Findings carry evidence, never verdicts. They sort by
``(severity rank, module, entity, entity_id, code)`` so reports are
deterministic for the same input.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "2"
TOOL_NAME = "zohokit"


class Severity(StrEnum):
    """Finding severity, ordered most to least severe."""

    ERROR = "error"
    REVIEW = "review"
    WARNING = "warning"
    INFO = "info"


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.ERROR: 0,
    Severity.REVIEW: 1,
    Severity.WARNING: 2,
    Severity.INFO: 3,
}


class Finding(BaseModel):
    """A single surfaced issue with source provenance."""

    model_config = ConfigDict(frozen=True)

    id: str
    module: str
    code: str
    severity: Severity
    entity: str
    entity_id: str
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    remediation: str = ""
    docs_url: str = ""

    def sort_key(self) -> tuple[int, str, str, str, str]:
        """Deterministic ordering key for report rendering."""
        return (
            _SEVERITY_RANK[self.severity],
            self.module,
            self.entity,
            self.entity_id,
            self.code,
        )


def sort_findings(findings: list[Finding]) -> list[Finding]:
    """Return findings in canonical report order."""
    return sorted(findings, key=lambda finding: finding.sort_key())


class ReportSummary(BaseModel):
    """Counts of findings by severity."""

    model_config = ConfigDict(frozen=True)

    error: int = 0
    review: int = 0
    warning: int = 0
    info: int = 0


class ReportSource(BaseModel):
    """Where the audited data came from (STD §3.5). Never raw org IDs."""

    model_config = ConfigDict(frozen=True)

    kind: str = "fixture"
    dc: str = "in"
    org_fingerprint: str = ""


class SideEffects(BaseModel):
    """Count of real-world side effects (always zero for audits)."""

    model_config = ConfigDict(frozen=True)

    external_writes: int = 0
    messages_sent: int = 0


class Report(BaseModel):
    """Versioned report envelope per STD §3.5."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = SCHEMA_VERSION
    tool: str = TOOL_NAME
    tool_version: str = "0.0.0"
    module: str
    run_id: str
    started_at: datetime
    finished_at: datetime
    mode: str = "offline"
    source: ReportSource = Field(default_factory=ReportSource)
    inputs_sha256: str = ""
    ready: bool
    summary: ReportSummary
    findings: list[Finding] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    side_effects: SideEffects = Field(default_factory=SideEffects)

    @classmethod
    def build(
        cls,
        *,
        module: str,
        run_id: str,
        started_at: datetime,
        finished_at: datetime,
        findings: list[Finding],
        ready: bool,
        mode: str = "offline",
        source: ReportSource | None = None,
        inputs_sha256: str = "",
        artifacts: dict[str, str] | None = None,
        side_effects: SideEffects | None = None,
    ) -> Report:
        """Build a report with findings sorted and the summary derived."""
        ordered = sort_findings(findings)
        summary = ReportSummary(
            error=sum(1 for item in ordered if item.severity is Severity.ERROR),
            review=sum(1 for item in ordered if item.severity is Severity.REVIEW),
            warning=sum(1 for item in ordered if item.severity is Severity.WARNING),
            info=sum(1 for item in ordered if item.severity is Severity.INFO),
        )
        return cls(
            module=module,
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            mode=mode,
            source=source or ReportSource(),
            inputs_sha256=inputs_sha256,
            ready=ready,
            summary=summary,
            findings=ordered,
            artifacts=artifacts or {},
            side_effects=side_effects or SideEffects(),
        )
