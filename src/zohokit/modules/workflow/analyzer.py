"""Static workflow linter over translated rule sets (UC-WF-1, TK-WF-F4).

Findings are keyed on stable entity IDs (rule IDs, ``Module.field``
names) — never positions — and the report carries the ID-uniqueness
invariant. Loop detection builds the write-graph (rule -> written
fields -> rules triggered by edits of those fields) and reports cycles
with their paths.
"""

from __future__ import annotations

from typing import Any

from zohokit.core.findings import Finding, Severity
from zohokit.modules.workflow.import_real import Unsupported
from zohokit.modules.workflow.language import Criterion, RulesetV2

_EDIT_EVENTS = frozenset({"record_edited", "field_changed", "stage_changed"})

#: Usage fraction of a configured limit that counts as "near".
NEAR_LIMIT_RATIO = 0.8


def _criterion_fields(node: Criterion | None) -> set[str]:
    if node is None:
        return set()
    found = set(_criterion_fields(child) for child in (*node.all, *node.any))
    out: set[str] = set()
    for part in found:
        out |= part
    if node.not_ is not None:
        out |= _criterion_fields(node.not_)
    if node.field:
        out.add(node.field)
    return out


def _written_fields(rule: Any) -> set[str]:
    out: set[str] = set()
    for action in rule.actions:
        if action.type == "field_update" and action.field:
            out.add(action.field)
        elif action.type == "assign_owner":
            out.add("Owner")
    return out


def _trigger_fields(rule: Any) -> set[str] | None:
    """Fields whose edit fires *rule*; None when it never fires on edit."""
    if rule.event.type == "record_edited":
        return set()
    if rule.event.type in ("field_changed", "stage_changed") and rule.event.field:
        return {rule.event.field}
    return None


def _trigger_key(rule: Any) -> tuple[str, str, str]:
    return (rule.module, rule.event.type, rule.execute_on)


def conflicting_field_updates(ruleset: RulesetV2) -> list[Finding]:
    """Two active rules, same trigger, same field, different values."""
    by_key: dict[tuple[str, str, str, str], dict[str, list[str]]] = {}
    for rule in ruleset.rules:
        if not rule.active:
            continue
        for action in rule.actions:
            if action.type != "field_update" or not action.field:
                continue
            key = (*_trigger_key(rule), action.field)
            by_key.setdefault(key, {}).setdefault(repr(action.value), []).append(rule.id)
    findings: list[Finding] = []
    for (module, _event, _on, field_name), by_value in sorted(by_key.items()):
        if len(by_value) < 2:
            continue
        rule_ids = sorted({rid for riders in by_value.values() for rid in riders})
        findings.append(
            Finding.create(
                module="workflow",
                code="conflicting_field_updates",
                severity=Severity.ERROR,
                entity="field",
                entity_id=f"{module}.{field_name}",
                message=(
                    f"{len(rule_ids)} active rules update {module}.{field_name} "
                    "on the same trigger with different values."
                ),
                evidence={"rule_ids": rule_ids},
                remediation="Keep one winning rule per trigger or gate the rest with criteria.",
                discriminator="conflict\0" + "\0".join(rule_ids),
            )
        )
    return findings


def potential_loops(ruleset: RulesetV2) -> list[Finding]:
    """Cycles in the rule -> written fields -> edit-triggered rules graph."""
    active = [rule for rule in ruleset.rules if rule.active]
    edges: dict[str, set[str]] = {rule.id: set() for rule in active}
    for source in active:
        written = _written_fields(source)
        if not written:
            continue
        for target in active:
            fields = _trigger_fields(target)
            if fields is None:
                continue
            if target.event.type == "record_edited" or (fields and written & fields):
                edges[source.id].add(target.id)
    # record_edited self-edge only counts when the rule writes (it does here).
    findings: list[Finding] = []
    seen: set[str] = set()
    ordered = sorted(edges)
    for start in ordered:
        stack: list[list[str]] = [[start]]
        while stack:
            path = stack.pop()
            for nxt in sorted(edges.get(path[-1], ())):
                if nxt == start and len(path) >= 1:
                    cycle = [*path, start]
                    key = "\0".join(sorted(set(cycle)))
                    if key not in seen:
                        seen.add(key)
                        first = sorted(set(cycle))[0]
                        findings.append(
                            Finding.create(
                                module="workflow",
                                code="potential_loop",
                                severity=Severity.ERROR,
                                entity="rule",
                                entity_id=first,
                                message=("Field-update chain can re-fire: " + " -> ".join(cycle)),
                                evidence={"path": cycle},
                                remediation="Gate one link with criteria or consolidate the rules.",
                                discriminator="loop\0" + "\0".join(sorted(set(cycle))),
                            )
                        )
                elif nxt not in path:
                    stack.append([*path, nxt])
    return sorted(findings, key=lambda item: item.id)


def stale_field_references(ruleset: RulesetV2, metadata: dict[str, set[str]]) -> list[Finding]:
    """Rule fields absent from the module metadata (UC-WF-1)."""
    findings: list[Finding] = []
    for rule in sorted(ruleset.rules, key=lambda item: item.id):
        known = metadata.get(rule.module, set())
        if not known:
            continue
        refs = set(_criterion_fields(rule.criteria))
        for action in rule.actions:
            if action.type == "field_update" and action.field:
                refs.add(action.field)
        if rule.event.field:
            refs.add(rule.event.field)
        for name in sorted(refs - known):
            findings.append(
                Finding.create(
                    module="workflow",
                    code="stale_field_reference",
                    severity=Severity.ERROR,
                    entity="field",
                    entity_id=f"{rule.module}.{name}",
                    message=(
                        f"Rule {rule.id} references {rule.module}.{name}, absent from metadata."
                    ),
                    evidence={"rule_id": rule.id},
                    remediation="Point the rule at a live field or remove it.",
                    discriminator="stale\0" + rule.id,
                )
            )
    return findings


def empty_rules(ruleset: RulesetV2) -> list[Finding]:
    """Active rules with no actions (UC-WF-1)."""
    return [
        Finding.create(
            module="workflow",
            code="empty_rule",
            severity=Severity.WARNING,
            entity="rule",
            entity_id=rule.id,
            message=f"Rule {rule.id} has no actions.",
            evidence={},
            remediation="Add an action or deactivate the rule.",
            discriminator="empty",
        )
        for rule in sorted(ruleset.rules, key=lambda item: item.id)
        if rule.active and not rule.actions
    ]


def dead_rules(ruleset: RulesetV2) -> list[Finding]:
    """Inactive rules that never fire (UC-WF-1)."""
    return [
        Finding.create(
            module="workflow",
            code="dead_rule",
            severity=Severity.WARNING,
            entity="rule",
            entity_id=rule.id,
            message=f"Rule {rule.id} is inactive and never fires.",
            evidence={},
            remediation="Reactivate the rule or delete it.",
            discriminator="dead",
        )
        for rule in sorted(ruleset.rules, key=lambda item: item.id)
        if not rule.active
    ]


def webhook_failings(ruleset: RulesetV2, failures: dict[str, str]) -> list[Finding]:
    """Rules whose webhook (by URL or real action ID) recently failed."""
    findings: list[Finding] = []
    for rule in sorted(ruleset.rules, key=lambda item: item.id):
        for action in rule.actions:
            if action.type != "webhook":
                continue
            reason = failures.get(action.url or "")
            if reason is None and action.ref_id:
                reason = failures.get(action.ref_id)
            if reason is None:
                continue
            findings.append(
                Finding.create(
                    module="workflow",
                    code="webhook_failing",
                    severity=Severity.ERROR,
                    entity="rule",
                    entity_id=rule.id,
                    message=f"Rule {rule.id} calls a webhook with recent failures.",
                    evidence={"reason": reason},
                    remediation="Fix the receiving endpoint, then re-enable the rule.",
                    discriminator="webhook\0" + (action.url or action.ref_id or ""),
                )
            )
    return findings


def near_limits(ruleset: RulesetV2, limits: dict[str, dict[str, int]]) -> list[Finding]:
    """Per-module action usage at >= 80% of the configured limit."""
    usage: dict[tuple[str, str], int] = {}
    for rule in ruleset.rules:
        if not rule.active:
            continue
        for action in rule.actions:
            key = (rule.module, action.type)
            usage[key] = usage.get(key, 0) + 1
    findings: list[Finding] = []
    for (module, action_type), count in sorted(usage.items()):
        limit = (limits.get(module) or {}).get(action_type)
        if limit is None or limit <= 0:
            continue
        if count / limit >= NEAR_LIMIT_RATIO:
            findings.append(
                Finding.create(
                    module="workflow",
                    code="near_limit",
                    severity=Severity.WARNING,
                    entity="module",
                    entity_id=module,
                    message=(f"{module} uses {count} of {limit} {action_type} actions."),
                    evidence={"action": action_type, "count": count, "limit": limit},
                    remediation="Consolidate actions before the limit blocks new rules.",
                    discriminator="limit\0" + action_type,
                )
            )
    return findings


def unsupported_constructs(missed: list[Unsupported]) -> list[Finding]:
    """Real-rule constructs with no simulator representation (UC-WF-3)."""
    findings: list[Finding] = []
    for item in sorted(missed, key=lambda entry: (entry.rule_id, entry.construct)):
        findings.append(
            Finding.create(
                module="workflow",
                code="unsupported_construct",
                severity=Severity.REVIEW,
                entity="rule",
                entity_id=item.rule_id,
                message=f"Rule {item.rule_id} uses an unsupported construct.",
                evidence={"construct": item.construct},
                remediation="Simulate an equivalent v2 rule by hand instead.",
                discriminator="unsupported\0" + item.construct,
            )
        )
    return findings


def lint(
    ruleset: RulesetV2,
    *,
    metadata: dict[str, set[str]] | None = None,
    webhook_failures: dict[str, str] | None = None,
    limits: dict[str, dict[str, int]] | None = None,
    unsupported: list[Unsupported] | None = None,
) -> list[Finding]:
    """Run every static check; IDs unique per (code, entity, discriminator)."""
    findings = [
        *conflicting_field_updates(ruleset),
        *potential_loops(ruleset),
        *empty_rules(ruleset),
        *dead_rules(ruleset),
    ]
    if metadata is not None:
        findings.extend(stale_field_references(ruleset, metadata))
    if webhook_failures:
        findings.extend(webhook_failings(ruleset, webhook_failures))
    if limits:
        findings.extend(near_limits(ruleset, limits))
    if unsupported:
        findings.extend(unsupported_constructs(unsupported))
    ids = [item.id for item in findings]
    if len(ids) != len(set(ids)):
        raise ValueError("lint finding IDs must be unique")
    return sorted(findings, key=lambda item: item.sort_key())


__all__: list[str] = [
    "conflicting_field_updates",
    "dead_rules",
    "empty_rules",
    "lint",
    "near_limits",
    "potential_loops",
    "stale_field_references",
    "unsupported_constructs",
    "webhook_failings",
]
