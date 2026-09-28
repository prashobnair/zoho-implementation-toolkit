"""Workflow simulator engine (TK-MIG-3).

Port of ``legacy/zoho-workflow-rule-testbench/engine.py``. Logic and legacy
output are unchanged.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any

from zohokit.core.context import RunContext
from zohokit.core.findings import Finding, Report, Severity
from zohokit.core.ids import canonical_json
from zohokit.modules import Analysis
from zohokit.modules.workflow.models import WorkflowInput
from zohokit.modules.workflow.report import build_report

ALLOWED_EVENTS = {"deal_created", "stage_changed", "followup_due"}
ALLOWED_ACTIONS = {"assign_owner", "set_stage", "queue_followup"}


def _validate_rules(rules: Any) -> list[dict[str, Any]]:
    if not isinstance(rules, list):
        raise ValueError("rules must be a list")
    ids: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("id"), str) or not rule["id"]:
            raise ValueError("Each rule requires an ID")
        if rule["id"] in ids:
            raise ValueError("Duplicate rule ID")
        ids.add(rule["id"])
        if rule.get("event") not in ALLOWED_EVENTS or rule.get("action") not in ALLOWED_ACTIONS:
            raise ValueError(f"Unsupported event/action for {rule['id']}")
        if not isinstance(rule.get("when", {}), dict):
            raise ValueError("when must be an object")
        if rule["action"] == "set_stage" and (
            not isinstance(rule.get("value"), str) or not rule["value"]
        ):
            raise ValueError("set_stage needs value")
    return rules


def _simulate(
    rules: list[dict[str, Any]],
    record: dict[str, Any],
    initial_event: str = "deal_created",
    max_steps: int = 20,
) -> dict[str, Any]:
    """Trace a single fictional deal, stop cycles and duplicate side effects."""
    _validate_rules(rules)
    if initial_event not in ALLOWED_EVENTS or not isinstance(record, dict):
        raise ValueError("Invalid initial event or record")
    if not isinstance(max_steps, int) or max_steps < 1:
        raise ValueError("max_steps must be positive")
    state = copy.deepcopy(record)
    pending = [initial_event]
    trace: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    visited: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    followups: set[tuple[str, str]] = set()
    steps = 0
    while pending:
        event = pending.pop(0)
        signature = (event, tuple(sorted((key, str(value)) for key, value in state.items())))
        if signature in visited:
            findings.append({"code": "cycle_detected", "event": event})
            break
        visited.add(signature)
        for rule in rules:
            if rule["event"] != event or any(
                state.get(key) != value for key, value in rule.get("when", {}).items()
            ):
                continue
            steps += 1
            if steps > max_steps:
                findings.append({"code": "step_limit", "rule": rule["id"]})
                pending.clear()
                break
            action = rule["action"]
            if action == "assign_owner":
                owner = rule.get("value")
                if not isinstance(owner, str) or not owner.strip():
                    findings.append({"code": "missing_owner", "rule": rule["id"]})
                    continue
                state["owner"] = owner
                trace.append({"rule": rule["id"], "action": action, "value": owner})
            elif action == "set_stage":
                target = rule["value"]
                if state.get("stage") == target:
                    findings.append({"code": "no_op_stage", "rule": rule["id"]})
                else:
                    state["stage"] = target
                    trace.append({"rule": rule["id"], "action": action, "value": target})
                    pending.append("stage_changed")
            else:
                token = (str(state.get("id", "")), str(rule.get("value", "followup")))
                if token in followups:
                    findings.append({"code": "duplicate_followup", "rule": rule["id"]})
                else:
                    followups.add(token)
                    trace.append({"rule": rule["id"], "action": action, "value": token[1]})
    return {
        "mode": "simulation_only",
        "state": state,
        "trace": trace,
        "findings": findings,
        "external_actions": 0,
    }


def _entity_id(item: dict[str, Any]) -> str:
    if isinstance(item.get("rule"), str):
        return str(item["rule"])
    if isinstance(item.get("event"), str):
        return str(item["event"])
    return str(item["code"])


def analyze(inputs: WorkflowInput) -> Analysis:
    """Simulate the trace; return findings plus the legacy result dict."""
    legacy = _simulate(
        copy.deepcopy(inputs.rules),
        copy.deepcopy(inputs.record),
        inputs.initial_event,
        inputs.max_steps,
    )
    created = tuple(
        Finding.create(
            module="workflow",
            code=item["code"],
            severity=Severity.ERROR,
            entity="trace",
            entity_id=_entity_id(item),
            message=_message(item),
            evidence={"legacy_finding": item},
            discriminator=str(item.get("rule", item.get("event", ""))),
        )
        for item in legacy["findings"]
    )
    return Analysis(findings=created, legacy=legacy, ready=not created)


def _message(item: dict[str, Any]) -> str:
    text: str = item["code"]
    if "rule" in item:
        text += f" (rule {item['rule']})"
    if "event" in item:
        text += f" (event {item['event']})"
    return text


def run(inputs: WorkflowInput, *, ctx: RunContext) -> Report:
    """Run the simulation: ``run(inputs, *, ctx) -> Report`` (TK-ARCH-1)."""
    analysis = analyze(inputs)
    digest = hashlib.sha256(
        canonical_json(inputs.model_dump(mode="json")).encode("utf-8")
    ).hexdigest()
    return build_report(analysis, ctx=ctx, inputs_sha256=digest)


__all__: list[str] = ["analyze", "run"]
