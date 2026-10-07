"""Explain a report envelope in plain English (TK-CORE-9).

Without ``--ai`` a deterministic template summarizes severity counts
plus one line per finding. With ``--ai`` the narrative comes from the
provider and must pass the STD-AI6/AI7 validators (every sentence cites
finding IDs with verbatim quotes; every number/date appears in the
report) or the template runs instead. The client audience never
includes internal-only fields (run IDs, hashes, artifact paths,
evidence values); finding IDs stay as citable references in both
audiences.
"""

from __future__ import annotations

from typing import Any, Literal

from jinja2 import Environment
from pydantic import BaseModel, ConfigDict, Field

from zohokit.ai.badge import AI_BADGE_CSS, ai_badge_html
from zohokit.ai.models import AiUsage
from zohokit.ai.pipeline import AiOutcome, AiRequest, run_ai
from zohokit.ai.prompts import load_template
from zohokit.ai.providers import LLMProvider
from zohokit.ai.schemas import ExplainDraft, ExplainSentence
from zohokit.ai.validators import check_citations, check_grounded, extract_report_tokens
from zohokit.core.findings import Report
from zohokit.core.redact import Redactor

Audience = Literal["internal", "client"]

#: Envelope keys that never reach a client audience.
INTERNAL_ENVELOPE_KEYS = ("run_id", "inputs_sha256", "artifacts")


class ExplainResult(BaseModel):
    """One explain run: suggestion sentences plus traceability (STD-AI5/9)."""

    model_config = ConfigDict(frozen=True)

    audience: str = "internal"
    source: str = "ai"
    model: str = ""
    prompt_version: str = "template"
    prompt_hash: str = ""
    ai_status: str = "template"
    sentences: list[ExplainSentence] = Field(default_factory=list)
    usage: AiUsage = Field(default_factory=AiUsage)


def filter_for_audience(report: Report, audience: Audience) -> dict[str, Any]:
    """Project a report to the fields an audience may see.

    The client view keeps severity counts, readiness and per-finding
    code/severity/message/remediation with redacted evidence; run IDs,
    hashes, artifact paths and raw evidence values never leave.
    """
    dumped = report.model_dump(mode="json")
    findings = []
    for item in dumped.get("findings", []):
        findings.append(
            {
                "id": item.get("id", ""),
                "code": item.get("code", ""),
                "severity": item.get("severity", ""),
                "message": item.get("message", ""),
                "remediation": item.get("remediation", ""),
            }
        )
    if audience == "client":
        redactor = Redactor()
        for entry in findings:
            entry["message"] = redactor.redact_obj(entry["message"])
            entry["remediation"] = redactor.redact_obj(entry["remediation"])
        return {
            "ready": dumped.get("ready"),
            "summary": dumped.get("summary", {}),
            "findings": findings,
        }
    full = [
        {
            "id": item.get("id", ""),
            "code": item.get("code", ""),
            "severity": item.get("severity", ""),
            "message": item.get("message", ""),
        }
        for item in dumped.get("findings", [])
    ]
    return {
        "ready": dumped.get("ready"),
        "summary": dumped.get("summary", {}),
        "findings": full,
    }


def template_summary(filtered: dict[str, Any]) -> ExplainDraft:
    """Deterministic summary: headline plus one cited line per finding."""
    summary = filtered.get("summary", {})
    headline = (
        f"Ready: {filtered.get('ready')}. "
        f"{summary.get('error', 0)} error, {summary.get('review', 0)} review, "
        f"{summary.get('warning', 0)} warning, {summary.get('info', 0)} info."
    )
    sentences = [ExplainSentence(text=headline, finding_ids=[], quotes=[], confidence=1.0)]
    for item in filtered.get("findings", []):
        text = f"[{item.get('severity')}] {item.get('code')}: {item.get('message')}"
        sentences.append(
            ExplainSentence(
                text=text,
                finding_ids=[item.get("id", "")],
                quotes=[item.get("message", "")],
                confidence=1.0,
            )
        )
    return ExplainDraft(sentences=sentences)


def explain_variables(filtered: dict[str, Any], audience: Audience) -> dict[str, str]:
    """Render deterministic prompt variables from the filtered view."""
    summary = filtered.get("summary", {})
    summary_text = (
        f"ready: {str(filtered.get('ready')).lower()}; "
        f"error: {summary.get('error', 0)}, review: {summary.get('review', 0)}, "
        f"warning: {summary.get('warning', 0)}, info: {summary.get('info', 0)}"
    )
    lines = [
        f"{item.get('id')} | {item.get('code')} | {item.get('severity')} | {item.get('message')}"
        for item in filtered.get("findings", [])
    ]
    return {
        "audience": audience,
        "report_summary": summary_text,
        "findings": "\n".join(lines),
    }


def validate_explain_draft(variables: dict[str, str], draft: ExplainDraft) -> list[str]:
    """Replay STD-AI6/AI7 on a draft; value-free violation strings."""
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
    allowed = extract_report_tokens(variables["report_summary"] + "\n" + findings_text)
    grounded = check_grounded(
        narrative="\n".join(sentence.text for sentence in draft.sentences),
        allowed=allowed,
    )
    violations.extend(f"grounding: {error}" for error in grounded.errors)
    return violations


def run_explain(
    report: Report,
    audience: Audience,
    *,
    provider: LLMProvider | None,
    allow_pii: bool = False,
    budget_tokens: int | None = None,
    temperature: float = 0.0,
    redactor: Redactor | None = None,
) -> ExplainResult:
    """Explain *report* for *audience*, via AI when a provider is set.

    ``provider`` None (or over budget, or a failed validation) runs the
    deterministic template with ``ai_status`` disabled/fallback.
    """
    filtered = filter_for_audience(report, audience)
    variables = explain_variables(filtered, audience)
    if provider is None:
        return ExplainResult(
            audience=audience,
            source="template",
            model="",
            prompt_version="template",
            prompt_hash="",
            ai_status="disabled",
            sentences=template_summary(filtered).sentences,
            usage=AiUsage(status="disabled"),
        )
    template = load_template("explain")
    outcome: AiOutcome[ExplainDraft] = run_ai(
        provider,
        AiRequest(
            template=template,
            variables=variables,
            allow_pii=allow_pii,
            budget_tokens=budget_tokens,
            temperature=temperature,
        ),
        ExplainDraft,
        fallback=lambda: template_summary(filtered),
        redactor=redactor,
    )
    if outcome.ai_status in ("ok", "repaired") and validate_explain_draft(variables, outcome.data):
        fallback_draft = template_summary(filtered)
        return ExplainResult(
            audience=audience,
            model=outcome.model,
            prompt_version=outcome.prompt_version,
            prompt_hash=outcome.prompt_hash,
            ai_status="fallback",
            sentences=fallback_draft.sentences,
            usage=outcome.usage.model_copy(update={"status": "fallback"}),
        )
    return ExplainResult(
        audience=audience,
        model=outcome.model,
        prompt_version=outcome.prompt_version,
        prompt_hash=outcome.prompt_hash,
        ai_status=outcome.ai_status,
        sentences=list(outcome.data.sentences),
        usage=outcome.usage,
    )


def render_explain_table(result: ExplainResult) -> str:
    """Human-readable sentence list."""
    lines = [f"audience: {result.audience} (source: {result.source}, status: {result.ai_status})"]
    for sentence in result.sentences:
        lines.append(f"- {sentence.text}")
    return "\n".join(lines) + "\n"


def render_explain_markdown(result: ExplainResult) -> str:
    """Markdown sentence list with an AI footer when applicable."""
    lines = [f"# Explanation ({result.audience})", ""]
    for sentence in result.sentences:
        lines.append(f"- {sentence.text}")
    lines.append("")
    if result.ai_status not in ("disabled", "template"):
        lines.append(
            f"_AI suggestion ({result.model}, {result.prompt_version}, status {result.ai_status})_"
        )
    else:
        lines.append("_Template summary (deterministic)_")
    return "\n".join(lines) + "\n"


_EXPLAIN_HTML = """\
<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Explanation ({{ audience }})</title>
<style>{{ badge_css }}body{font-family:sans-serif;max-width:60em;margin:2em auto;}</style>
</head><body>
<h1>Explanation ({{ audience }})</h1>
<p>source: {{ source }} · status: {{ ai_status }}</p>
<p>model: {{ model }} · prompt: {{ prompt_version }}</p>
<ul>
{% for sentence in sentences %}
<li>{{ sentence.text }}{{ badge(sentence.confidence) }}<br>
<small>cites: {{ sentence.finding_ids | join(", ") }}</small></li>
{% endfor %}
</ul>
</body></html>
"""


def render_explain_html(result: ExplainResult) -> str:
    """HTML sentences; AI items carry the suggestion badge + confidence."""
    template = Environment(autoescape=True).from_string(_EXPLAIN_HTML)
    show_badge = result.ai_status not in ("disabled", "template")
    return template.render(
        audience=result.audience,
        source=result.source,
        ai_status=result.ai_status,
        model=result.model,
        prompt_version=result.prompt_version,
        sentences=[
            {
                "text": item.text,
                "finding_ids": item.finding_ids,
                "confidence": item.confidence,
            }
            for item in result.sentences
        ],
        badge=(lambda confidence: ai_badge_html(confidence))
        if show_badge
        else (lambda confidence: ""),
        badge_css=AI_BADGE_CSS,
    )


__all__: list[str] = [
    "Audience",
    "ExplainResult",
    "explain_variables",
    "filter_for_audience",
    "render_explain_html",
    "render_explain_markdown",
    "render_explain_table",
    "run_explain",
    "template_summary",
    "validate_explain_draft",
]
