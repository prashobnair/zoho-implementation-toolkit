"""Trend diff between two report envelopes, keyed by stable finding ID."""

from __future__ import annotations

from dataclasses import dataclass

from zohokit.core.findings import Finding, Report, Severity
from zohokit.core.ids import canonical_json


@dataclass(frozen=True)
class ReportDiff:
    """New, resolved and changed findings from ``before`` to ``after``."""

    new: tuple[Finding, ...] = ()
    resolved: tuple[Finding, ...] = ()
    changed: tuple[tuple[Finding, Finding], ...] = ()

    @property
    def new_errors(self) -> tuple[Finding, ...]:
        """New findings with ``error`` severity (block promotion)."""
        return tuple(item for item in self.new if item.severity is Severity.ERROR)


def _key(finding: Finding) -> str:
    return finding.id


def _shape(finding: Finding) -> str:
    return canonical_json(finding.model_dump(mode="json"))


def diff_reports(before: Report, after: Report) -> ReportDiff:
    """Compare two reports by stable finding ID.

    ``new`` holds findings only in ``after``; ``resolved`` only in
    ``before``; ``changed`` holds ``(old, new)`` pairs whose content
    differs under the same ID (for example a suppression flip or an
    evidence update). Order follows the reports' canonical ordering.
    """
    old = {_key(item): item for item in before.findings}
    current = {_key(item): item for item in after.findings}
    new = tuple(item for item in after.findings if item.id not in old)
    resolved = tuple(item for item in before.findings if item.id not in current)
    changed = tuple(
        (old[item.id], item)
        for item in after.findings
        if item.id in old and _shape(old[item.id]) != _shape(item)
    )
    return ReportDiff(new=new, resolved=resolved, changed=changed)


@dataclass(frozen=True)
class DiffSummary:
    """Counts rendered by every diff output format."""

    new: int = 0
    resolved: int = 0
    changed: int = 0
    new_errors: int = 0


def summarize(diff: ReportDiff) -> DiffSummary:
    """Count a diff for rendering and exit-code decisions."""
    return DiffSummary(
        new=len(diff.new),
        resolved=len(diff.resolved),
        changed=len(diff.changed),
        new_errors=len(diff.new_errors),
    )


def render_diff_json(before: Report, after: Report, diff: ReportDiff) -> str:
    """Machine-readable diff (finding IDs plus full finding payloads)."""
    payload = {
        "schema_version": "1",
        "tool": "zohokit",
        "before_run_id": before.run_id,
        "after_run_id": after.run_id,
        "summary": {
            "new": len(diff.new),
            "resolved": len(diff.resolved),
            "changed": len(diff.changed),
            "new_errors": len(diff.new_errors),
        },
        "new": [item.model_dump(mode="json") for item in diff.new],
        "resolved": [item.model_dump(mode="json") for item in diff.resolved],
        "changed": [
            {"before": old.model_dump(mode="json"), "after": new_.model_dump(mode="json")}
            for old, new_ in diff.changed
        ],
    }
    return canonical_json(payload)


def render_diff_table(diff: ReportDiff) -> str:
    """Human-readable diff table."""
    summary = summarize(diff)
    lines = [
        "zohokit report diff",
        f"new: {summary.new}  resolved: {summary.resolved}  "
        f"changed: {summary.changed}  new errors: {summary.new_errors}",
        "",
    ]
    for label, items in (("new", diff.new), ("resolved", diff.resolved)):
        lines.append(f"## {label} ({len(items)})")
        for item in items:
            lines.append(
                f"- [{item.severity}] {item.code} {item.entity}/{item.entity_id} {item.id}"
            )
        lines.append("")
    lines.append(f"## changed ({len(diff.changed)})")
    for old, new_ in diff.changed:
        lines.append(
            f"- [{new_.severity}] {new_.code} {new_.entity}/{new_.entity_id} {new_.id}"
            f" (was severity {old.severity})"
            if old.severity != new_.severity
            else f"- [{new_.severity}] {new_.code} {new_.entity}/{new_.entity_id} {new_.id}"
        )
    return "\n".join(lines).rstrip() + "\n"


def render_diff_markdown(before: Report, after: Report, diff: ReportDiff) -> str:
    """Markdown diff for PR comments and chatops."""
    summary = summarize(diff)
    lines = [
        "# Report diff",
        "",
        f"Before `{before.run_id}` → after `{after.run_id}`: "
        f"**{summary.new} new**, **{summary.resolved} resolved**, "
        f"**{summary.changed} changed** ({summary.new_errors} new errors).",
        "",
    ]
    for label, items in (("New", diff.new), ("Resolved", diff.resolved)):
        lines.append(f"## {label} ({len(items)})")
        lines.append("")
        if not items:
            lines.append("None.")
            lines.append("")
            continue
        lines.append("| Severity | Code | Entity | ID |")
        lines.append("| --- | --- | --- | --- |")
        for item in items:
            lines.append(
                f"| {item.severity} | `{item.code}` | "
                f"{item.entity}/{item.entity_id} | `{item.id}` |"
            )
        lines.append("")
    lines.append(f"## Changed ({len(diff.changed)})")
    lines.append("")
    if not diff.changed:
        lines.append("None.")
    else:
        lines.append("| Code | Entity | ID | Note |")
        lines.append("| --- | --- | --- | --- |")
        for old, new_ in diff.changed:
            note = "severity changed" if old.severity != new_.severity else "content changed"
            lines.append(
                f"| `{new_.code}` | {new_.entity}/{new_.entity_id} | `{new_.id}` | {note} |"
            )
    return "\n".join(lines).rstrip() + "\n"


__all__: list[str] = [
    "DiffSummary",
    "ReportDiff",
    "diff_reports",
    "render_diff_json",
    "render_diff_markdown",
    "render_diff_table",
    "summarize",
]
