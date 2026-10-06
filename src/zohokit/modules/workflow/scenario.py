"""Scenario test runner with rule/branch coverage (UC-WF-2, TK-WF-F5/F6).

A scenario file is YAML: ``rules`` (v2 or legacy v1) plus ``cases``
(``given`` record + event, ``then`` assertions). ``params`` expands one
case into many (each entry merges into ``given.record``). Every case
runs the deterministic simulator; assertion mismatches become
``scenario_case_failed`` error findings and unfired rules become
``uncovered_rule`` info findings. Rule coverage is the share of rules
that fired at least once; branch coverage is the share of rules whose
criteria evaluated both true and false across the suite.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from zohokit.core.findings import Finding, Severity
from zohokit.modules.workflow.engine import analyze
from zohokit.modules.workflow.language import RulesetV2, parse_ruleset
from zohokit.modules.workflow.models import WorkflowInput
from zohokit.modules.workflow.simulator import eval_criterion


@dataclass(frozen=True)
class CaseResult:
    """One executed scenario case (deterministic, value-free diffs)."""

    name: str
    passed: bool
    failures: tuple[str, ...] = ()
    fired: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SuiteResult:
    """A whole scenario file run, with coverage (TK-WF-F6)."""

    file: str
    cases: tuple[CaseResult, ...] = ()
    rule_coverage: float = 0.0
    branch_coverage: float = 0.0
    covered_rules: tuple[str, ...] = ()
    uncovered_rules: tuple[str, ...] = ()
    rule_ids: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        """Every case passed (coverage never fails a suite by itself)."""
        return all(case.passed for case in self.cases)


def _expand_params(case: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    params = case.get("params")
    if not params:
        return [(str(case.get("name", "case")), case)]
    out = []
    for index, entry in enumerate(params):
        if not isinstance(entry, dict):
            continue
        merged = copy.deepcopy(case)
        merged.pop("params", None)
        record = merged.setdefault("given", {}).setdefault("record", {})
        for key, value in entry.items():
            if key == "name":
                continue
            record[key] = value
        label = str(entry.get("name", f"param-{index}"))
        out.append((f"{case.get('name', 'case')}[{label}]", merged))
    return out


def _check_state(actual: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    failures = []
    for key, value in expected.items():
        if actual.get(key) != value:
            failures.append(f"state field {key} differs")
    return failures


def run_suite(path: str | Path) -> SuiteResult:
    """Load one scenario YAML file and run every case (pure, deterministic)."""
    source = Path(path)
    try:
        doc = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read scenario {source.name}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("rules"), list):
        raise ValueError(f"scenario {source.name} needs a rules list")
    rules = doc["rules"]
    kind, parsed = parse_ruleset(copy.deepcopy(rules))
    rule_ids = tuple(str(item.get("id", "")) for item in rules if isinstance(item, dict))
    fired_all: set[str] = set()
    criteria_seen: dict[str, set[bool]] = {rid: set() for rid in rule_ids}
    results: list[CaseResult] = []
    for raw in doc.get("cases", []) or []:
        if not isinstance(raw, dict):
            continue
        for name, case in _expand_params(raw):
            given = case.get("given", {}) if isinstance(case.get("given"), dict) else {}
            then = case.get("then", {}) if isinstance(case.get("then"), dict) else {}
            record = given.get("record", {})
            event = str(given.get("event", "record_created"))
            max_steps = int(given.get("max_steps", 20))
            changed = [str(item) for item in given.get("fields_changed", []) or []]
            raw_field = given.get("event_field")
            inputs = WorkflowInput(
                rules=copy.deepcopy(rules),
                record=record if isinstance(record, dict) else {},
                initial_event=event,
                max_steps=max_steps,
                initial_fields_changed=changed,
                event_field=str(raw_field) if raw_field is not None else None,
            )
            analysis = analyze(inputs)
            legacy = analysis.legacy
            trace = legacy.get("trace", [])
            fired = tuple(sorted({str(step.get("rule", "")) for step in trace}))
            fired_all.update(fired)
            if kind == "v2" and isinstance(parsed, RulesetV2):
                state_record = dict(record) if isinstance(record, dict) else {}
                for rule in parsed.rules:
                    outcome = eval_criterion(rule.criteria, state_record, set(changed), {})
                    criteria_seen.setdefault(rule.id, set()).add(outcome)
            failures: list[str] = []
            codes = sorted(finding.code for finding in analysis.findings)
            if "state" in then and isinstance(then["state"], dict):
                failures.extend(_check_state(legacy.get("state", {}), then["state"]))
            if "fired" in then:
                want = sorted(str(item) for item in then["fired"])
                if sorted(fired) != want:
                    failures.append(f"fired rules differ (want {len(want)}, got {len(fired)})")
            if "findings" in then:
                want_codes = sorted(str(item) for item in then["findings"])
                if codes != want_codes:
                    failures.append(
                        f"finding codes differ (want {len(want_codes)}, got {len(codes)})"
                    )
            if then.get("no_findings") and codes:
                failures.append(f"expected no findings, got {len(codes)}")
            results.append(
                CaseResult(
                    name=name,
                    passed=not failures,
                    failures=tuple(failures),
                    fired=fired,
                    findings=tuple(codes),
                )
            )
    uncovered = tuple(sorted(set(rule_ids) - fired_all))
    covered = tuple(sorted(fired_all & set(rule_ids)))
    rule_coverage = len(covered) / len(rule_ids) if rule_ids else 1.0
    branches = 0
    for rid in rule_ids:
        seen = criteria_seen.get(rid, set())
        branches += 1 if (True in seen and False in seen) or rid in fired_all else 0
    branch_coverage = branches / len(rule_ids) if rule_ids else 1.0
    return SuiteResult(
        file=source.name,
        cases=tuple(results),
        rule_coverage=rule_coverage,
        branch_coverage=branch_coverage,
        covered_rules=covered,
        uncovered_rules=uncovered,
        rule_ids=rule_ids,
    )


def suite_findings(suite: SuiteResult) -> list[Finding]:
    """Case failures plus one ``uncovered_rule`` info per unfired rule."""
    findings: list[Finding] = []
    for case in suite.cases:
        if not case.passed:
            findings.append(
                Finding.create(
                    module="workflow",
                    code="scenario_case_failed",
                    severity=Severity.ERROR,
                    entity="scenario",
                    entity_id=case.name,
                    message=f"Scenario case failed with {len(case.failures)} mismatch(s).",
                    evidence={"failures": list(case.failures)},
                    remediation="Fix the rule or correct the expected trace.",
                    discriminator="case\0" + suite.file,
                )
            )
    for rid in suite.uncovered_rules:
        findings.append(
            Finding.create(
                module="workflow",
                code="uncovered_rule",
                severity=Severity.INFO,
                entity="rule",
                entity_id=rid,
                message=f"No scenario case exercised rule {rid}.",
                evidence={"suite": suite.file},
                remediation="Add a scenario case that fires the rule.",
                discriminator="uncovered\0" + suite.file,
            )
        )
    return findings


def run_directory(path: str | Path) -> list[SuiteResult]:
    """Run every ``*.yaml``/``*.yml`` suite in *path* (sorted, deterministic)."""
    root = Path(path)
    if not root.is_dir():
        raise ValueError(f"scenario directory missing: {root}")
    files = sorted([*root.glob("*.yaml"), *root.glob("*.yml")])
    if not files:
        raise ValueError(f"no scenario files in {root}")
    return [run_suite(item) for item in files]


__all__: list[str] = [
    "CaseResult",
    "SuiteResult",
    "run_directory",
    "run_suite",
    "suite_findings",
]
