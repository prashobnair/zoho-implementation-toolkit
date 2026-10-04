"""Manifest v2 analysis: diff, inference, risk, order, rollback (TK-REL-3..7).

Finding identities are content-based (component IDs, edge triples,
canonical cycles) — never positional — so IDs stay stable across runs.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from zohokit.core.context import RunContext
from zohokit.core.findings import Finding, Report, Severity
from zohokit.core.ids import canonical_json
from zohokit.core.plan import Plan
from zohokit.modules.release.deploy import DeployPlan, plan_deploy
from zohokit.modules.release.diff import ManifestDiff, diff_manifests
from zohokit.modules.release.infer import Edge, infer_edges
from zohokit.modules.release.manifest import (
    EXPERIMENTAL_KINDS,
    Component,
    Manifest,
    manifest_fingerprint,
)
from zohokit.modules.release.risk import Risk, RiskLevel, assess, release_risk
from zohokit.modules.release.rollback import is_data_losing, rollback_plan

#: Behavior kinds reuse the v1 finding code for continuity.
_SENSITIVE = {"workflow", "validation", "function", "webhook"}


@dataclass(frozen=True)
class ManifestAnalysis:
    """Everything the v2 diff computes: findings plus review artifacts."""

    findings: tuple[Finding, ...]
    diff: ManifestDiff
    edges: tuple[Edge, ...]
    risks: tuple[Risk, ...]
    release_risk: RiskLevel
    deploy: DeployPlan
    rollback: Plan
    fingerprint: str
    ready: bool


def _make(
    code: str,
    severity: Severity,
    entity_id: str,
    message: str,
    discriminator: str,
    evidence: dict[str, object] | None = None,
) -> Finding:
    return Finding.create(
        module="release",
        code=code,
        severity=severity,
        entity="manifest",
        entity_id=entity_id,
        message=message,
        evidence=dict(evidence or {}),
        discriminator=discriminator,
    )


def _positive_count(value: object) -> bool:
    """A numeric usage count above zero (booleans are not counts)."""
    if isinstance(value, bool):
        return value
    return isinstance(value, (int, float)) and value > 0


def analyze_manifest(before: list[Component], after: list[Component]) -> ManifestAnalysis:
    """Diff two manifests and score every change."""
    old = {item.component_id(): item for item in before}
    new = {item.component_id(): item for item in after}
    diff = diff_manifests(before, after)
    edges = infer_edges(after)
    risks = tuple(
        assess(change, before_attributes=dict(old[change.component_id].attributes))
        if change.component_id in old
        else assess(change)
        for change in diff.changes
    )
    deploy = plan_deploy(diff, list(edges))
    findings: list[Finding] = []
    for change in diff.changes:
        if change.change == "removed":
            findings.append(
                _make(
                    "removal_review",
                    Severity.ERROR,
                    change.component_id,
                    f"removal_review: {change.component_id} was removed",
                    change.component_id,
                )
            )
            if is_data_losing(change):
                findings.append(
                    _make(
                        "irreversible_change",
                        Severity.REVIEW,
                        change.component_id,
                        f"irreversible_change: restoring {change.component_id} "
                        "cannot recover stored values",
                        change.component_id,
                    )
                )
            if change.kind == "picklist_value":
                prior = old.get(change.component_id)
                attributes = dict(prior.attributes) if prior is not None else {}
                in_use = attributes.get("in_use") is True or _positive_count(
                    attributes.get("in_use_count")
                )
                if in_use:
                    findings.append(
                        _make(
                            "picklist_value_in_use",
                            Severity.ERROR,
                            change.component_id,
                            f"picklist_value_in_use: {change.component_id} "
                            "is still referenced by records",
                            change.component_id,
                        )
                    )
        elif change.change in ("added", "changed") and change.kind in _SENSITIVE:
            findings.append(
                _make(
                    "behavior_regression_review",
                    Severity.ERROR,
                    change.component_id,
                    f"behavior_regression_review: {change.component_id} was {change.change}",
                    change.component_id,
                )
            )
        if (
            change.kind == "field"
            and change.change == "changed"
            and any(entry.attribute == "data_type" for entry in change.attributes)
        ):
            findings.append(
                _make(
                    "field_type_change",
                    Severity.ERROR,
                    change.component_id,
                    f"field_type_change: {change.component_id} changed type",
                    f"{change.component_id}\0data_type",
                )
            )
    for edge in edges:
        if edge.confidence == "heuristic" and edge.target in new:
            findings.append(
                _make(
                    "heuristic_dependency",
                    Severity.INFO,
                    edge.source,
                    f"heuristic_dependency: {edge.source} may use {edge.target} "
                    f"(seen in {edge.via})",
                    f"{edge.source}\0{edge.target}\0{edge.via}",
                    {"via": edge.via, "target": edge.target},
                )
            )
    for item in sorted(after, key=lambda entry: entry.component_id()):
        if item.kind in EXPERIMENTAL_KINDS:
            findings.append(
                _make(
                    "experimental_kind",
                    Severity.WARNING,
                    item.component_id(),
                    f"experimental_kind: {item.component_id()} is experimental",
                    item.component_id(),
                )
            )
    existing = set(new)
    for edge in edges:
        if edge.confidence == "declared" and edge.target not in existing:
            findings.append(
                _make(
                    "missing_dependency",
                    Severity.ERROR,
                    edge.source,
                    f"missing_dependency: {edge.source} needs {edge.target}",
                    f"{edge.source}\0{edge.target}",
                    {"dependency": edge.target},
                )
            )
    for cycle in deploy.cycles:
        findings.append(
            _make(
                "dependency_cycle",
                Severity.ERROR,
                cycle[0],
                f"dependency_cycle: {' -> '.join(cycle)}",
                "|".join(cycle),
                {"cycle": list(cycle)},
            )
        )
    ordered = sorted(findings, key=lambda item: item.sort_key())
    ready = not any(item.severity in (Severity.ERROR, Severity.REVIEW) for item in ordered)
    return ManifestAnalysis(
        findings=tuple(ordered),
        diff=diff,
        edges=tuple(edges),
        risks=risks,
        release_risk=release_risk(list(risks)),
        deploy=deploy,
        rollback=rollback_plan(list(diff.changes), old),
        fingerprint=manifest_fingerprint(Manifest(components=list(after))),
        ready=ready,
    )


def analyze_drift(approved: list[Component], live: list[Component]) -> ManifestAnalysis:
    """Compare approved manifests against a live snapshot (TK-REL-10).

    Every addition, removal or change versus the approved set is an
    ``unapproved_drift`` error and nothing else: the drift gate reports
    one finding per unapproved change. The shared v2 machinery still
    provides attribute diffs, risk and deploy context for review.
    """
    base = analyze_manifest(approved, live)
    drifted = diff_manifests(approved, live)
    findings = sorted(
        (
            _make(
                "unapproved_drift",
                Severity.ERROR,
                change.component_id,
                f"unapproved_drift: {change.component_id} was {change.change} "
                "outside an approved promotion",
                f"{change.component_id}\0{change.change}",
            )
            for change in drifted.changes
        ),
        key=lambda item: item.sort_key(),
    )
    ready = not findings
    return ManifestAnalysis(
        findings=tuple(findings),
        diff=base.diff,
        edges=base.edges,
        risks=base.risks,
        release_risk=base.release_risk,
        deploy=base.deploy,
        rollback=base.rollback,
        fingerprint=base.fingerprint,
        ready=ready,
    )


def run_manifest(
    before: list[Component], after: list[Component], *, ctx: RunContext
) -> tuple[Report, ManifestAnalysis]:
    """Run the v2 diff and build the versioned envelope."""
    analysis = analyze_manifest(before, after)
    digest = hashlib.sha256(
        canonical_json(
            {
                "before": [item.model_dump(mode="json") for item in before],
                "after": [item.model_dump(mode="json") for item in after],
            }
        ).encode("utf-8")
    ).hexdigest()
    report = Report.build(
        module="release",
        run_id=digest,
        started_at=ctx.now,
        finished_at=ctx.now,
        findings=list(analysis.findings),
        ready=analysis.ready,
        mode=ctx.mode,
        inputs_sha256=digest,
    )
    return report, analysis


__all__: list[str] = ["ManifestAnalysis", "analyze_drift", "analyze_manifest", "run_manifest"]
