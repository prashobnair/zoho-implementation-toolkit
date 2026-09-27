"""Forms parity engine (TK-MIG-3).

Port of ``legacy/zoho-forms-parity-checker/parity.py`` with one intentional
fix (TK-FIX-5): visibility is evaluated in dependency order. A field is
visible only if its referenced field is visible **and** matches; answers to
hidden fields are ignored and reported as ``answer_for_hidden_field`` info.
Fields in a ``visible_if`` cycle get a ``visibility_cycle`` error and are
treated as hidden (fail closed).
"""

from __future__ import annotations

import copy
import hashlib
from decimal import Decimal, InvalidOperation
from typing import Any

from zohokit.core.context import RunContext
from zohokit.core.findings import Finding, Report, Severity
from zohokit.core.ids import canonical_json
from zohokit.modules import Analysis
from zohokit.modules.forms.models import FormsInput
from zohokit.modules.forms.report import build_report

SUPPORTED = {"text", "number", "select", "calculated"}


def _validate_schema(fields: Any) -> set[str]:
    if not isinstance(fields, list):
        raise ValueError("fields must be a list")
    names: set[str] = set()
    for field in fields:
        if (
            not isinstance(field, dict)
            or not isinstance(field.get("name"), str)
            or not field["name"]
        ):
            raise ValueError("Every field needs a name")
        if field["name"] in names:
            raise ValueError("Duplicate field name")
        names.add(field["name"])
        if field.get("type") not in SUPPORTED:
            raise ValueError(f"Unsupported type for {field['name']}")
        cond = field.get("visible_if")
        if cond is not None and (not isinstance(cond, dict) or len(cond) != 1):
            raise ValueError("visible_if must contain exactly one field/value")
        if field["type"] == "calculated" and field.get("operation") not in {"multiply", "add"}:
            raise ValueError("Only multiply/add calculations are supported")
    return names


def _visibility(
    fields: list[dict[str, Any]], names: set[str], answers: dict[str, Any]
) -> tuple[dict[str, bool], set[str]]:
    """Compute per-field visibility in dependency order (TK-FIX-5).

    Returns the visibility map and the set of fields in a ``visible_if``
    cycle (treated as hidden, fail closed).
    """
    by_name = {field["name"]: field for field in fields}
    deps: dict[str, set[str]] = {}
    for field in fields:
        cond = field.get("visible_if")
        ref = next(iter(cond)) if isinstance(cond, dict) else None
        deps[field["name"]] = {ref} if ref in names and ref != field["name"] else set()
    # Deterministic Kahn topological order over the dependency edges.
    order: list[str] = []
    pending = {name: set(parents) for name, parents in deps.items()}
    ready = sorted(name for name, parents in pending.items() if not parents)
    while ready:
        name = ready.pop(0)
        order.append(name)
        for other in sorted(pending):
            if name in pending[other]:
                pending[other].remove(name)
                if not pending[other]:
                    ready.append(other)
        ready.sort()
    cyclic = set(names) - set(order)
    for name in sorted(cyclic):
        order.append(name)
    visible: dict[str, bool] = {}
    for name in order:
        if name in cyclic:
            visible[name] = False
            continue
        cond = by_name[name].get("visible_if")
        if cond is None:
            visible[name] = True
            continue
        ref, expected = next(iter(cond.items()))
        if ref not in names or ref == name:
            visible[name] = False
            continue
        visible[name] = bool(visible.get(ref, True)) and answers.get(ref) == expected
    return visible, cyclic


def _evaluate(
    fields: list[dict[str, Any]],
    answers: dict[str, Any],
    *,
    side: str,
    case: str,
) -> tuple[dict[str, Any], list[Finding]]:
    """Evaluate one side; return the legacy result plus new-style findings."""
    names = _validate_schema(fields)
    if not isinstance(answers, dict):
        raise ValueError("answers must be an object")
    visible, cyclic = _visibility(fields, names, answers)
    hidden = {name for name, shown in visible.items() if not shown}
    effective = {key: value for key, value in answers.items() if key not in hidden}
    new_findings: list[Finding] = []
    for position, name in enumerate(sorted(cyclic)):
        new_findings.append(
            Finding.create(
                module="forms",
                code="visibility_cycle",
                severity=Severity.ERROR,
                entity="schema",
                entity_id=f"{side}:{name}",
                message=f"Field {name!r} is in a visible_if cycle and is treated as hidden.",
                evidence={"field": name},
                discriminator=str(position),
            )
        )
    for position, name in enumerate(
        field["name"] for field in fields if field["name"] in hidden and field["name"] in answers
    ):
        new_findings.append(
            Finding.create(
                module="forms",
                code="answer_for_hidden_field",
                severity=Severity.INFO,
                entity="case",
                entity_id=f"{case}:{side}:{name}",
                message=f"Answer for hidden field {name!r} was ignored.",
                evidence={"field": name},
                discriminator=str(position),
            )
        )
    output: dict[str, Any] = {}
    issues: list[dict[str, Any]] = []
    for field in fields:
        name = field["name"]
        condition = field.get("visible_if")
        if name in cyclic:
            issues.append({"field": name, "code": "visibility_cycle"})
            continue
        if not visible[name]:
            if condition is not None and (
                not isinstance(condition, dict)
                or _ref(condition) not in names
                or _ref(condition) == name
            ):
                issues.append({"field": name, "code": "invalid_visibility_reference"})
            continue
        value = effective.get(name)
        if field["type"] == "calculated":
            operands = field.get("sources", [])
            if (
                not isinstance(operands, list)
                or len(operands) != 2
                or any(source not in names for source in operands)
            ):
                issues.append({"field": name, "code": "invalid_calculation_sources"})
                continue
            try:
                first, second = (Decimal(str(effective[source])) for source in operands)
                value = first * second if field["operation"] == "multiply" else first + second
                value = str(value)
            except (KeyError, InvalidOperation, TypeError):
                issues.append({"field": name, "code": "invalid_number"})
                continue
        elif value is None or value == "":
            if field.get("required"):
                issues.append({"field": name, "code": "required_missing"})
            continue
        elif field["type"] == "select" and value not in field.get("options", []):
            issues.append({"field": name, "code": "invalid_choice"})
            continue
        elif field["type"] == "number":
            try:
                value = str(Decimal(str(value)))
            except InvalidOperation:
                issues.append({"field": name, "code": "invalid_number"})
                continue
        output[name] = value
    return {"output": output, "issues": issues}, new_findings


def _ref(condition: dict[str, Any]) -> Any:
    """The single referenced field of a visibility condition."""
    return next(iter(condition.items()))[0]


def _compare_legacy(
    spec: dict[str, Any],
) -> tuple[dict[str, Any], list[Finding]]:
    if not isinstance(spec, dict) or not isinstance(spec.get("cases"), list):
        raise ValueError("Expected source_fields, target_fields and cases")
    source, target = spec["source_fields"], spec["target_fields"]
    _validate_schema(source)
    _validate_schema(target)
    results: list[dict[str, Any]] = []
    new_findings: list[Finding] = []
    for case in spec["cases"]:
        if not isinstance(case, dict) or not isinstance(case.get("answers"), dict):
            raise ValueError("Each case needs answers")
        case_name = str(case.get("name", ""))
        left, left_new = _evaluate(source, case["answers"], side="source", case=case_name)
        right, right_new = _evaluate(target, case["answers"], side="target", case=case_name)
        new_findings.extend(left_new)
        new_findings.extend(right_new)
        results.append(
            {"case": case.get("name", ""), "pass": left == right, "source": left, "target": right}
        )
    legacy = {
        "mode": "offline_simulation",
        "all_pass": all(item["pass"] for item in results),
        "cases": results,
        "form_submissions": 0,
    }
    return legacy, new_findings


def analyze(inputs: FormsInput) -> Analysis:
    """Compare the form pair; return findings plus the legacy result dict."""
    spec = copy.deepcopy(inputs.model_dump())
    legacy, new_findings = _compare_legacy(spec)
    ready = bool(legacy["all_pass"]) and not any(
        finding.severity is Severity.ERROR for finding in new_findings
    )
    return Analysis(findings=tuple(new_findings), legacy=legacy, ready=ready)


def run(inputs: FormsInput, *, ctx: RunContext) -> Report:
    """Run the parity check: ``run(inputs, *, ctx) -> Report`` (TK-ARCH-1)."""
    analysis = analyze(inputs)
    digest = hashlib.sha256(
        canonical_json(inputs.model_dump(mode="json")).encode("utf-8")
    ).hexdigest()
    return build_report(analysis, ctx=ctx, inputs_sha256=digest)


__all__: list[str] = ["analyze", "run"]
