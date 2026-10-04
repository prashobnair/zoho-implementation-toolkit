"""PR-comment rendering for the release gate (TK-REL-8).

One Markdown document of at most 65,000 characters: a readiness banner,
the release risk level, collapsible finding details, the attribute
diffs, and the deploy order. Longer reports are cut deterministically
(canonical finding order, tail first) with a truncation note that says
exactly how much was omitted. The hidden marker lets the GitHub Action
find and update its own comment instead of posting a duplicate.
"""

from __future__ import annotations

from zohokit.core.findings import Report
from zohokit.modules.release.deploy import DeployPlan
from zohokit.modules.release.diff import ManifestDiff
from zohokit.modules.release.risk import RiskLevel

#: Hidden marker: the action finds its sticky comment by this string.
COMMENT_MARKER = "<!-- zohokit-release-gate -->"

#: GitHub PR comment ceiling for the gate body.
MAX_COMMENT_CHARS = 65000


def _finding_block(finding_id: str, code: str, entity: str, message: str) -> str:
    return (
        f"<details><summary><code>{code}</code> {entity} <code>{finding_id}</code></summary>\n\n"
        f"{message}\n\n</details>"
    )


def render_pr_comment(
    report: Report,
    diff: ManifestDiff,
    deploy: DeployPlan,
    release_risk: RiskLevel,
) -> str:
    """Render the sticky PR comment body (banner, findings, order)."""
    banner = "READY" if report.ready else "NOT READY"
    summary = report.summary
    head = [
        COMMENT_MARKER,
        f"# Release gate: {banner}",
        "",
        f"Risk **{release_risk}** — {len(diff.added)} added, {len(diff.removed)} removed, "
        f"{len(diff.changed)} changed. Findings: {summary.error} error, "
        f"{summary.review} review, {summary.warning} warning, {summary.info} info"
        + (f", {summary.suppressed} suppressed" if summary.suppressed else "")
        + ".",
        "",
        "## Findings",
        "",
    ]
    ordered = sorted(report.findings, key=lambda item: item.sort_key())
    blocks = [
        _finding_block(
            finding.id,
            finding.code,
            f"{finding.entity}/{finding.entity_id}",
            finding.message,
        )
        for finding in ordered
    ]
    middle: list[str] = []
    if diff.attribute_notes:
        middle.append("## Changed attributes")
        middle.append("")
        middle.append("<details><summary>attribute diffs</summary>")
        middle.append("")
        middle.extend(f"- `{note}`" for note in diff.attribute_notes)
        middle.append("")
        middle.append("</details>")
        middle.append("")
    tail = ["## Deploy order", ""]
    if deploy.cycles:
        tail.append("No safe order: dependency cycle detected.")
        tail.append("")
    else:
        for position, component_id in enumerate(deploy.deploy, start=1):
            tail.append(f"{position}. `{component_id}`")
        if deploy.removals:
            tail.append("")
            tail.append("Removals (dependents first):")
            tail.append("")
            for position, component_id in enumerate(deploy.removals, start=1):
                tail.append(f"{position}. `{component_id}`")
        if not deploy.deploy and not deploy.removals:
            tail.append("No deployable changes.")
        tail.append("")
    full = "\n".join([*head, *blocks, "", *middle, *tail]).rstrip() + "\n"
    if len(full) <= MAX_COMMENT_CHARS:
        return full
    return _truncate(head, blocks, middle, tail, len(ordered))


def _truncate(
    head: list[str], blocks: list[str], middle: list[str], tail: list[str], total: int
) -> str:
    """Drop finding blocks from the tail until the body fits the ceiling."""
    kept = list(blocks)
    omitted = 0
    while kept:
        remaining = total - len(kept)
        note = (
            f"> Truncated: {remaining} of {total} findings omitted (full report attached as JSON)."
        )
        trial = "\n".join([*head, *kept, "", note, "", *middle, *tail]).rstrip() + "\n"
        if len(trial) <= MAX_COMMENT_CHARS:
            return trial
        kept.pop()
        omitted += 1
    note = f"> Truncated: {total} of {total} findings omitted (full report attached as JSON)."
    text = "\n".join([*head, note, "", *middle, *tail]).rstrip() + "\n"
    if len(text) > MAX_COMMENT_CHARS:
        text = text[: MAX_COMMENT_CHARS - 100].rstrip() + "\n<!-- truncated -->\n"
    return text


__all__: list[str] = ["COMMENT_MARKER", "MAX_COMMENT_CHARS", "render_pr_comment"]
