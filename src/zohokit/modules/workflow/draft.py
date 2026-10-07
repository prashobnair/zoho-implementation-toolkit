"""Natural-language rule drafts + loop explanations (AI-WF-1/2, UC-WF-4).

A description becomes a draft v2 rule JSON (schema-validated, abstain
when unsure), simulated immediately with its trace, never deployed. A
detected loop is explained in plain English citing the rule chain
through the AI-core citation + grounding validators. With no provider
the deterministic path runs (template abstention / template loop
summary) and reports ``AI disabled``.

Action targets are grounded in the description (STD-AI10): every
webhook ``url``, email ``template`` and ``assign_owner`` ``owner`` must
appear in the description (case-insensitive, separator-insensitive
substring; for URLs the host counts as well) or in a caller-supplied
allowlist, otherwise the draft falls back to an abstention.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Collection
from typing import Any
from urllib.parse import urlsplit

from jinja2 import Environment
from pydantic import BaseModel, ConfigDict, Field

from zohokit.ai.badge import AI_BADGE_CSS, ai_badge_html
from zohokit.ai.models import AiUsage
from zohokit.ai.pipeline import AiOutcome, AiRequest, run_ai
from zohokit.ai.prompts import load_template
from zohokit.ai.providers import LLMProvider
from zohokit.ai.schemas import ExplainSentence, LoopExplanation, RuleDraft
from zohokit.ai.validators import check_citations, check_grounded, extract_report_tokens
from zohokit.core.findings import Finding
from zohokit.core.ids import canonical_json
from zohokit.core.redact import Redactor
from zohokit.modules.workflow.language import V2_ACTIONS, RulesetV2, RuleV2
from zohokit.modules.workflow.simulator import simulate_v2

#: Confidence below which a draft must abstain (AI-WF-1).
ABSTAIN_BELOW = 0.6

#: Demo field list used when the caller passes no metadata.
DEFAULT_DRAFT_FIELDS: tuple[tuple[str, str], ...] = (
    ("Stage", "picklist"),
    ("Amount", "currency"),
    ("Owner", "user"),
    ("Deal_Name", "string"),
    ("Lead_Source", "picklist"),
    ("Closing_Date", "date"),
)


class DraftResult(BaseModel):
    """One NL-to-draft run: suggestion plus traceability (STD-AI5)."""

    model_config = ConfigDict(frozen=True)

    source: str = "template"
    model: str = ""
    prompt_version: str = "template"
    prompt_hash: str = ""
    ai_status: str = "template"
    description: str = ""
    draft: RuleDraft = Field(default_factory=RuleDraft)
    violations: tuple[str, ...] = ()
    usage: AiUsage = Field(default_factory=AiUsage)


class LoopExplainResult(BaseModel):
    """One loop explanation: sentences plus traceability (STD-AI5)."""

    model_config = ConfigDict(frozen=True)

    source: str = "template"
    model: str = ""
    prompt_version: str = "template"
    prompt_hash: str = ""
    ai_status: str = "template"
    sentences: tuple[ExplainSentence, ...] = ()
    usage: AiUsage = Field(default_factory=AiUsage)


def _source_for(ai_status: str) -> str:
    """``ai`` only when a model produced the content, else ``template``."""
    return "ai" if ai_status in ("ok", "repaired") else "template"


def draft_variables(description: str, fields: dict[str, str] | None = None) -> dict[str, str]:
    """Render deterministic prompt variables for one description."""
    resolved = fields if fields else dict(DEFAULT_DRAFT_FIELDS)
    lines = [f"{name} ({dtype})" for name, dtype in sorted(resolved.items())]
    return {"description": description, "field_list": "\n".join(lines)}


def _rule_fields(rule: dict[str, Any]) -> set[str]:
    """Every field api_name a draft rule references."""
    found: set[str] = set()
    event = rule.get("event", {})
    if isinstance(event, dict) and event.get("field"):
        found.add(str(event["field"]))
    nodes = [rule.get("criteria")] if rule.get("criteria") else []
    while nodes:
        node = nodes.pop()
        if not isinstance(node, dict):
            continue
        for key in ("all", "any"):
            children = node.get(key, [])
            if isinstance(children, list):
                nodes.extend(children)
        inner = node.get("not")
        if isinstance(inner, dict):
            nodes.append(inner)
        if node.get("field"):
            found.add(str(node["field"]))
    for action in rule.get("actions", []) or []:
        if isinstance(action, dict) and action.get("field"):
            found.add(str(action["field"]))
    return found


def validate_draft(
    fields: set[str],
    draft: RuleDraft,
    *,
    description: str,
    allow_targets: Collection[str] = (),
) -> list[str]:
    """Guardrails for one draft; value-free violation strings."""
    violations: list[str] = []
    if draft.abstain:
        if draft.rule:
            violations.append("abstention: abstained draft carries a rule")
        return violations
    if not draft.rule:
        violations.append("coverage: no rule drafted and no abstention")
        return violations
    try:
        RuleV2.model_validate(draft.rule)
    except Exception:
        violations.append("reference: rule fails the v2 language schema")
        return violations
    for name in sorted(_rule_fields(draft.rule)):
        if name not in fields:
            violations.append("reference: unknown field")
            break
    for action in draft.rule.get("actions", []) or []:
        if isinstance(action, dict) and action.get("type") not in V2_ACTIONS:
            violations.append("reference: unknown action type")
            break
    violations.extend(check_action_grounding(description, draft.rule, allow_targets=allow_targets))
    if draft.confidence < ABSTAIN_BELOW:
        violations.append("abstention: drafted below the confidence floor")
    return violations


#: Separator runs collapse to one space so ``regional-manager`` matches
#: ``regional manager`` (STD-AI10 grounding, case-insensitive).
_SEPARATOR_RE = re.compile(r"[^0-9a-z]+")


def _normalized(text: str) -> str:
    """Case-fold *text* with every separator run collapsed to one space."""
    return _SEPARATOR_RE.sub(" ", text.casefold()).strip()


def _target_allowed(target: str, allow_targets: Collection[str]) -> bool:
    """Whether *target* is named verbatim in the caller allowlist."""
    lowered = target.casefold()
    return any(entry.casefold() == lowered for entry in allow_targets)


def _url_host(url: str) -> str:
    """Hostname of *url*, or ``""`` when it has none."""
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


def check_action_grounding(
    description: str,
    rule: dict[str, Any],
    *,
    allow_targets: Collection[str] = (),
) -> list[str]:
    """Every action target must be mentioned in *description* (STD-AI10).

    Each webhook ``url``, email ``template`` and ``assign_owner``
    ``owner`` must appear in the description as a case-insensitive,
    separator-insensitive substring (for URLs the host counts as well)
    or match a caller-supplied allowlist entry, otherwise the draft is
    rejected as a possible prompt injection. Value-free violation
    strings only.
    """
    norm_description = _normalized(description)
    allowed = tuple(allow_targets or ())
    for action in rule.get("actions", []) or []:
        if not isinstance(action, dict):
            continue
        kind = action.get("type")
        targets = []
        if kind == "webhook":
            url = str(action.get("url") or "")
            if not url:
                continue
            targets = [url]
            host = _url_host(url)
            if host:
                targets.append(host)
        elif kind == "send_email":
            template = str(action.get("template") or "")
            if not template:
                continue
            targets = [template]
        elif kind == "assign_owner":
            owner = str(action.get("owner") or "")
            if not owner:
                continue
            targets = [owner]
        else:
            continue
        grounded = any(
            (normed := _normalized(target))
            and (normed in norm_description or _target_allowed(target, allowed))
            for target in targets
        )
        if not grounded:
            return ["grounding: action target not in description"]
    return []


def _fallback_draft() -> RuleDraft:
    """Deterministic abstention used with no provider or on failure."""
    return RuleDraft(confidence=0.0, rationale="", abstain=True, abstain_reason="no draft")


def suggest_draft(
    description: str,
    fields: dict[str, str] | None = None,
    *,
    provider: LLMProvider | None,
    allow_pii: bool = False,
    budget_tokens: int | None = None,
    redactor: Redactor | None = None,
    allow_targets: Collection[str] = (),
) -> DraftResult:
    """Draft one rule from *description*; validated, simulated-ready."""
    known = set(fields) if fields else {name for name, _ in DEFAULT_DRAFT_FIELDS}
    template = load_template("workflow_draft")
    outcome: AiOutcome[RuleDraft] = run_ai(
        provider,
        AiRequest(
            template=template,
            variables=draft_variables(description, fields),
            allow_pii=allow_pii,
            budget_tokens=budget_tokens,
        ),
        RuleDraft,
        fallback=_fallback_draft,
        redactor=redactor,
    )
    allowed = tuple(allow_targets or ())
    violations = validate_draft(known, outcome.data, description=description, allow_targets=allowed)
    if violations and outcome.ai_status in ("ok", "repaired"):
        abstained = _fallback_draft()
        return DraftResult(
            source="template",
            model=outcome.model,
            prompt_version=outcome.prompt_version,
            prompt_hash=outcome.prompt_hash,
            ai_status="fallback",
            description=description,
            draft=abstained,
            violations=tuple(violations),
            usage=outcome.usage.model_copy(update={"status": "fallback"}),
        )
    return DraftResult(
        source=_source_for(outcome.ai_status),
        model=outcome.model,
        prompt_version=outcome.prompt_version,
        prompt_hash=outcome.prompt_hash,
        ai_status=outcome.ai_status,
        description=description,
        draft=outcome.data,
        violations=tuple(violations),
        usage=outcome.usage,
    )


def loop_variables(path: list[str], messages: dict[str, str], note: str = "") -> dict[str, str]:
    """Render deterministic prompt variables for one loop chain."""
    chain = " -> ".join(path)
    lines = [f"{rid} | potential_loop | error | {messages.get(rid, '')}" for rid in path[:-1]]
    return {"loop_chain": chain, "findings": "\n".join(lines), "note": note}


def validate_loop_explanation(variables: dict[str, str], draft: LoopExplanation) -> list[str]:
    """Replay STD-AI6/AI7 on a loop draft; value-free violation strings."""
    violations: list[str] = []
    findings_text = variables["findings"]
    valid_ids = {line.split(" | ", 1)[0] for line in findings_text.splitlines() if " | " in line}
    citations = check_citations(
        cited_ids=[fid for sentence in draft.sentences for fid in sentence.finding_ids],
        quotes=[quote for sentence in draft.sentences for quote in sentence.quotes],
        valid_ids=valid_ids,
        source_text=findings_text,
    )
    violations.extend(f"citation: {error}" for error in citations.errors)
    allowed = extract_report_tokens(variables["loop_chain"] + "\n" + findings_text)
    grounded = check_grounded(
        narrative="\n".join(sentence.text for sentence in draft.sentences),
        allowed=allowed,
    )
    violations.extend(f"grounding: {error}" for error in grounded.errors)
    return violations


def _fallback_loop(path: list[str]) -> LoopExplanation:
    """Deterministic one-line-per-link summary (no provider)."""
    sentences = [
        ExplainSentence(
            text=f"Rule {rid} can re-fire through this chain.",
            finding_ids=[rid],
            quotes=[rid],
            confidence=1.0,
        )
        for rid in path[:-1]
    ]
    return LoopExplanation(sentences=sentences)


def explain_loop(
    path: list[str],
    messages: dict[str, str],
    *,
    provider: LLMProvider | None,
    allow_pii: bool = False,
    budget_tokens: int | None = None,
    redactor: Redactor | None = None,
) -> LoopExplainResult:
    """Explain one loop *path* in plain English, chain cited."""
    variables = loop_variables(path, messages)
    template = load_template("workflow_loop")
    outcome: AiOutcome[LoopExplanation] = run_ai(
        provider,
        AiRequest(
            template=template,
            variables=variables,
            allow_pii=allow_pii,
            budget_tokens=budget_tokens,
        ),
        LoopExplanation,
        fallback=lambda: _fallback_loop(path),
        redactor=redactor,
    )
    if outcome.ai_status in ("ok", "repaired") and validate_loop_explanation(
        variables, outcome.data
    ):
        fallback_draft = _fallback_loop(path)
        return LoopExplainResult(
            source="template",
            model=outcome.model,
            prompt_version=outcome.prompt_version,
            prompt_hash=outcome.prompt_hash,
            ai_status="fallback",
            sentences=tuple(fallback_draft.sentences),
            usage=outcome.usage.model_copy(update={"status": "fallback"}),
        )
    return LoopExplainResult(
        source=_source_for(outcome.ai_status),
        model=outcome.model,
        prompt_version=outcome.prompt_version,
        prompt_hash=outcome.prompt_hash,
        ai_status=outcome.ai_status,
        sentences=tuple(outcome.data.sentences),
        usage=outcome.usage,
    )


def explain_lint_loops(
    findings: list[Finding],
    *,
    provider: LLMProvider | None,
    allow_pii: bool = False,
    budget_tokens: int | None = None,
    redactor: Redactor | None = None,
) -> list[Finding]:
    """Attach a cited loop explanation to each ``potential_loop`` finding.

    The explanation (AI-WF-2, citation + grounding validated) lands in an
    ``ai`` block on the finding evidence; finding IDs are untouched
    (evidence never feeds the discriminator). With no provider the
    findings return unchanged.
    """
    if provider is None:
        return list(findings)
    explained: list[Finding] = []
    for finding in findings:
        if finding.code != "potential_loop":
            explained.append(finding)
            continue
        evidence = finding.evidence or {}
        raw_path = evidence.get("path", [])
        path = [str(item) for item in raw_path if str(item)] if isinstance(raw_path, list) else []
        if not path:
            explained.append(finding)
            continue
        messages = {rid: finding.message for rid in path}
        result = explain_loop(
            path,
            messages,
            provider=provider,
            allow_pii=allow_pii,
            budget_tokens=budget_tokens,
            redactor=redactor,
        )
        merged = {**evidence, "ai": result.model_dump(mode="json")}
        explained.append(finding.model_copy(update={"evidence": merged}))
    return explained


#: Small synthetic Marigold deal used when ``draft`` gets no ``--record``.
DEFAULT_DRAFT_RECORD: dict[str, Any] = {
    "id": "555000000000000001",
    "Deal_Name": "Marigold Sample Deal",
    "Stage": "Qualification",
    "Amount": 25000,
    "Owner": "regional-manager",
    "Lead_Source": "Web",
    "Closing_Date": "2026-12-31",
}


class DraftOutput(BaseModel):
    """One ``workflow draft`` run: the draft plus its immediate simulation.

    ``simulation`` is the full deterministic trace of the drafted rule
    against the record (``None`` when the run abstained); ``deployed``
    is always ``False`` — drafts never write anything.
    """

    model_config = ConfigDict(frozen=True)

    description: str = ""
    source: str = "template"
    model: str = ""
    prompt_version: str = "template"
    prompt_hash: str = ""
    ai_status: str = "template"
    draft: RuleDraft = Field(default_factory=RuleDraft)
    violations: tuple[str, ...] = ()
    simulation: dict[str, Any] | None = None
    deployed: bool = False
    note: str = "draft only, not deployed"
    usage: AiUsage = Field(default_factory=AiUsage)


def simulate_draft(rule: dict[str, Any], record: dict[str, Any]) -> dict[str, Any] | None:
    """Simulate one drafted *rule* against *record*; ``None`` when empty."""
    if not rule:
        return None
    try:
        parsed = RuleV2.model_validate(rule)
    except Exception:
        return None
    return simulate_v2(
        RulesetV2(rules=(parsed,)),
        copy.deepcopy(record),
        parsed.event.type,
    )


def build_draft_output(
    result: DraftResult,
    record: dict[str, Any],
) -> DraftOutput:
    """Pair a draft *result* with its immediate simulation trace."""
    simulation = None
    if not result.draft.abstain and result.draft.rule:
        simulation = simulate_draft(result.draft.rule, record)
    return DraftOutput(
        description=result.description,
        source=result.source,
        model=result.model,
        prompt_version=result.prompt_version,
        prompt_hash=result.prompt_hash,
        ai_status=result.ai_status,
        draft=result.draft,
        violations=result.violations,
        simulation=simulation,
        usage=result.usage,
    )


def render_draft_table(output: DraftOutput) -> str:
    """Human-readable draft plus its simulation trace."""
    lines = [
        f"description: {output.description} (source: {output.source}, status: {output.ai_status})",
        f"model: {output.model or '—'} · prompt: {output.prompt_version} "
        f"{output.prompt_hash or '—'}",
    ]
    if output.draft.abstain:
        lines.append(f"abstained: {output.draft.abstain_reason or 'no draft'}")
    else:
        lines.append(f"draft rule: {canonical_json(output.draft.rule)}")
    for violation in output.violations:
        lines.append(f"! violation: {violation}")
    if output.simulation is not None:
        trace = output.simulation.get("trace", [])
        external = output.simulation.get("external_actions", 0)
        lines.append(f"simulation: {len(trace)} step(s), {external} external")
        for step in trace:
            lines.append(
                f"- {step.get('step')}: rule {step.get('rule')} {step.get('action')} "
                f"(day {step.get('day')}, caused by {step.get('caused_by')})"
            )
        for item in output.simulation.get("findings", []):
            lines.append(f"! sim finding: {item.get('code')}")
    else:
        lines.append("simulation: none (abstained)")
    lines.append(output.note)
    return "\n".join(lines) + "\n"


def render_draft_markdown(output: DraftOutput) -> str:
    """Markdown draft plus its simulation trace."""
    lines = ["# Workflow draft", "", output.note, ""]
    lines.append(f"- description: {output.description}")
    lines.append(f"- source: {output.source} · status: {output.ai_status}")
    lines.append(f"- model: {output.model or '—'} · prompt: {output.prompt_version}")
    if output.draft.abstain:
        lines.append(f"- abstained: {output.draft.abstain_reason or 'no draft'}")
    else:
        lines.append(f"- confidence: {output.draft.confidence:.2f}")
        lines.append("")
        lines.append("```json")
        lines.append(canonical_json(output.draft.rule))
        lines.append("```")
    if output.violations:
        lines.append("")
        lines.append("## Violations")
        lines.extend(f"- {violation}" for violation in output.violations)
    lines.append("")
    lines.append("## Simulation")
    if output.simulation is not None:
        trace = output.simulation.get("trace", [])
        lines.append(f"{len(trace)} step(s).")
        for step in trace:
            lines.append(
                f"- {step.get('step')}: rule {step.get('rule')} {step.get('action')} "
                f"(day {step.get('day')}, caused by {step.get('caused_by')})"
            )
        for item in output.simulation.get("findings", []):
            lines.append(f"- sim finding: {item.get('code')}")
    else:
        lines.append("none (abstained).")
    return "\n".join(lines) + "\n"


_DRAFT_HTML = """\
<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Workflow draft</title>
<style>{{ badge_css }}body{font-family:sans-serif;max-width:60em;margin:2em auto;}
table{border-collapse:collapse;}td,th{border:1px solid #ccc;padding:0.3em 0.6em;}</style>
</head><body>
<h1>Workflow draft {{ badge }}</h1>
<p>{{ note }}</p>
<p>description: {{ description }}</p>
<p>source: {{ source }} · status: {{ ai_status }}</p>
<p>model: {{ model }} · prompt: {{ prompt_version }}</p>
{% if abstain %}
<p>abstained: {{ abstain_reason }}</p>
{% else %}
<p>confidence: {{ confidence }}</p>
<pre>{{ rule_json }}</pre>
{% endif %}
{% if violations %}
<h2>Violations</h2>
<ul>{% for violation in violations %}<li>{{ violation }}</li>{% endfor %}</ul>
{% endif %}
<h2>Simulation</h2>
{% if simulation is none %}
<p>none (abstained).</p>
{% else %}
<p>{{ step_count }} step(s).</p>
<table><tr><th>step</th><th>rule</th><th>action</th><th>day</th><th>caused by</th></tr>
{% for step in steps %}
<tr><td>{{ step.step }}</td><td>{{ step.rule }}</td><td>{{ step.action }}</td>
<td>{{ step.day }}</td><td>{{ step.caused_by }}</td></tr>
{% endfor %}
</table>
{% endif %}
</body></html>
"""


def render_draft_html(output: DraftOutput) -> str:
    """HTML draft; AI content carries the suggestion badge + confidence."""
    template = Environment(autoescape=True).from_string(_DRAFT_HTML)
    show_badge = output.ai_status not in ("disabled", "template", "fallback")
    badge = ai_badge_html(output.draft.confidence) if show_badge else ""
    steps = []
    if output.simulation is not None:
        for step in output.simulation.get("trace", []):
            steps.append(
                {
                    "step": step.get("step", ""),
                    "rule": step.get("rule", ""),
                    "action": step.get("action", ""),
                    "day": step.get("day", 0),
                    "caused_by": step.get("caused_by", ""),
                }
            )
    return template.render(
        badge=badge,
        badge_css=AI_BADGE_CSS,
        note=output.note,
        description=output.description,
        source=output.source,
        ai_status=output.ai_status,
        model=output.model or "—",
        prompt_version=output.prompt_version,
        abstain=output.draft.abstain,
        abstain_reason=output.draft.abstain_reason or "no draft",
        confidence=f"{output.draft.confidence:.2f}",
        rule_json=canonical_json(output.draft.rule),
        violations=list(output.violations),
        simulation=output.simulation,
        step_count=len(steps),
        steps=steps,
    )


__all__: list[str] = [
    "ABSTAIN_BELOW",
    "DEFAULT_DRAFT_FIELDS",
    "DEFAULT_DRAFT_RECORD",
    "DraftOutput",
    "DraftResult",
    "LoopExplainResult",
    "build_draft_output",
    "check_action_grounding",
    "draft_variables",
    "explain_lint_loops",
    "explain_loop",
    "loop_variables",
    "render_draft_html",
    "render_draft_markdown",
    "render_draft_table",
    "simulate_draft",
    "suggest_draft",
    "validate_draft",
    "validate_loop_explanation",
]
