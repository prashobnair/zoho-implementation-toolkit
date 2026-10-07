"""Natural-language rule drafts + loop explanations (AI-WF-1/2, UC-WF-4).

A description becomes a draft v2 rule JSON (schema-validated, abstain
when unsure), simulated immediately with its trace, never deployed. A
detected loop is explained in plain English citing the rule chain
through the AI-core citation + grounding validators. With no provider
the deterministic path runs (template abstention / template loop
summary) and reports ``AI disabled``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from zohokit.ai.models import AiUsage
from zohokit.ai.pipeline import AiOutcome, AiRequest, run_ai
from zohokit.ai.prompts import load_template
from zohokit.ai.providers import LLMProvider
from zohokit.ai.schemas import ExplainSentence, LoopExplanation, RuleDraft
from zohokit.ai.validators import check_citations, check_grounded, extract_report_tokens
from zohokit.core.redact import Redactor
from zohokit.modules.workflow.language import V2_ACTIONS, RuleV2

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

    source: str = "ai"
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

    source: str = "ai"
    model: str = ""
    prompt_version: str = "template"
    prompt_hash: str = ""
    ai_status: str = "template"
    sentences: tuple[ExplainSentence, ...] = ()
    usage: AiUsage = Field(default_factory=AiUsage)


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


def validate_draft(fields: set[str], draft: RuleDraft) -> list[str]:
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
    if draft.confidence < ABSTAIN_BELOW:
        violations.append("abstention: drafted below the confidence floor")
    return violations


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
    violations = validate_draft(known, outcome.data)
    if violations and outcome.ai_status in ("ok", "repaired"):
        abstained = _fallback_draft()
        return DraftResult(
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
            model=outcome.model,
            prompt_version=outcome.prompt_version,
            prompt_hash=outcome.prompt_hash,
            ai_status="fallback",
            sentences=tuple(fallback_draft.sentences),
            usage=outcome.usage.model_copy(update={"status": "fallback"}),
        )
    return LoopExplainResult(
        model=outcome.model,
        prompt_version=outcome.prompt_version,
        prompt_hash=outcome.prompt_hash,
        ai_status=outcome.ai_status,
        sentences=tuple(outcome.data.sentences),
        usage=outcome.usage,
    )


__all__: list[str] = [
    "ABSTAIN_BELOW",
    "DEFAULT_DRAFT_FIELDS",
    "DraftResult",
    "LoopExplainResult",
    "draft_variables",
    "explain_loop",
    "loop_variables",
    "suggest_draft",
    "validate_draft",
    "validate_loop_explanation",
]
