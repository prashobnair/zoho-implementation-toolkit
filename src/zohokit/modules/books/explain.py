"""Controller narrative for Books month-end recon (AI-BK-1, UC-BK-4).

``run_books_explain`` turns a recon report into a finance narrative
("3 deals (₹4.2L) missing invoices; 1 invoice in wrong entity…") where
every figure is verified against the report (STD-AI7): citations replay
STD-AI6, plain numbers/dates replay STD-AI7 on money-blanked text, and
scale-suffixed amounts (``₹4.2L``/``lakh``/``Cr``/``crore``/``$1.2k``/
``1.2M``) must equal a report amount at their own stated precision.
Every error-severity finding's entity must be cited — omitting one is a
coverage violation. With no provider the deterministic template runs
(``source: "template"``, ``ai_status: "disabled"``).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from zohokit.ai.models import AiUsage
from zohokit.ai.pipeline import AiOutcome, AiRequest, run_ai
from zohokit.ai.prompts import load_template
from zohokit.ai.providers import LLMProvider
from zohokit.ai.schemas import ExplainDraft, ExplainSentence
from zohokit.ai.validators import (
    MoneyFigure,
    check_citations,
    check_grounded,
    check_money_grounded,
    extract_report_tokens,
    strip_money_figures,
)
from zohokit.core.findings import Report, Severity
from zohokit.core.redact import Redactor

#: Approval verdicts a safe narrative must never assert (STD-AI10).
INJECTION_VERDICTS = ("approved", "auto-approve", "will approve")


class BooksExplainResult(BaseModel):
    """One controller-narrative run with traceability (STD-AI5/9)."""

    model_config = ConfigDict(frozen=True)

    source: str = "template"
    model: str = ""
    prompt_version: str = "template"
    prompt_hash: str = ""
    ai_status: str = "template"
    sentences: list[ExplainSentence] = Field(default_factory=list)
    usage: AiUsage = Field(default_factory=AiUsage)


def recon_variables(report: Report) -> dict[str, str]:
    """Render deterministic prompt variables from a recon report."""
    dumped = report.model_dump(mode="json")
    summary = dumped.get("summary", {})
    summary_text = (
        f"ready: {str(dumped.get('ready')).lower()}; "
        f"error: {summary.get('error', 0)}, review: {summary.get('review', 0)}, "
        f"warning: {summary.get('warning', 0)}, info: {summary.get('info', 0)}"
    )
    lines = []
    amounts: list[str] = []
    for item in dumped.get("findings", []):
        evidence = item.get("evidence") or {}
        lines.append(
            f"{item.get('id')} | {item.get('code')} | {item.get('severity')} | "
            f"{item.get('entity')}:{item.get('entity_id')} | {item.get('message')}"
        )
        for key in ("deal_net", "invoiced_total", "converted", "original"):
            if evidence.get(key) not in (None, ""):
                amounts.append(str(evidence[key]))
        for entry in evidence.get("conversions") or []:
            if isinstance(entry, dict):
                for key in ("original", "converted"):
                    if entry.get(key) not in (None, ""):
                        amounts.append(str(entry[key]))
    return {
        "report_summary": summary_text,
        "amounts": ", ".join(amounts),
        "findings": "\n".join(lines),
    }


def report_money_figures(variables: dict[str, str]) -> list[MoneyFigure]:
    """Report amounts a narrative may restate (exact Decimal values)."""
    from decimal import Decimal, InvalidOperation

    figures: list[MoneyFigure] = []
    for token in variables["amounts"].replace(",", " ").split():
        try:
            value = Decimal(token)
        except InvalidOperation:
            continue
        figures.append(MoneyFigure(value=value, precision=Decimal("0.01")))
    for token in extract_report_tokens(
        variables["report_summary"] + "\n" + variables["findings"]
    ).numbers:
        try:
            value = Decimal(token)
        except InvalidOperation:
            continue
        figures.append(MoneyFigure(value=value, precision=Decimal("1")))
    return figures


def _valid_ids(variables: dict[str, str]) -> set[str]:
    return {line.split(" | ", 1)[0] for line in variables["findings"].splitlines() if " | " in line}


def validate_books_explain(variables: dict[str, str], draft: ExplainDraft) -> list[str]:
    """Replay STD-AI6/AI7 (with Indian-notation money) on a draft."""
    violations: list[str] = []
    findings_text = variables["findings"]
    citations = check_citations(
        cited_ids=[fid for sentence in draft.sentences for fid in sentence.finding_ids],
        quotes=[quote for sentence in draft.sentences for quote in sentence.quotes],
        valid_ids=_valid_ids(variables),
        source_text=findings_text,
    )
    violations.extend(f"citation: {error}" for error in citations.errors)
    narrative = "\n".join(sentence.text for sentence in draft.sentences)
    stripped = strip_money_figures(narrative)
    allowed = extract_report_tokens(variables["report_summary"] + "\n" + findings_text)
    grounded = check_grounded(narrative=stripped, allowed=allowed)
    violations.extend(f"grounding: {error}" for error in grounded.errors)
    money = check_money_grounded(narrative=narrative, allowed=report_money_figures(variables))
    violations.extend(f"money: {error}" for error in money.errors)
    cited_ids = {fid for sentence in draft.sentences for fid in sentence.finding_ids}
    cited_text = narrative
    for line in findings_text.splitlines():
        parts = line.split(" | ")
        if len(parts) < 5:
            continue
        finding_id, _code, severity, entity = parts[0], parts[1], parts[2], parts[3]
        if severity != Severity.ERROR.value:
            continue
        if finding_id not in cited_ids and entity not in cited_text:
            violations.append("coverage: error-severity finding entity not cited")
            break
    return violations


def injection_followed(raw: str) -> bool:
    """True when the raw response asserts an approval verdict (STD-AI10)."""
    lowered = raw.lower()
    return any(verdict in lowered for verdict in INJECTION_VERDICTS)


def template_narrative(report: Report) -> ExplainDraft:
    """Deterministic controller summary with exact report figures."""
    dumped = report.model_dump(mode="json")
    summary = dumped.get("summary", {})
    errors = [item for item in dumped.get("findings", []) if item.get("severity") == "error"]
    reviews = [item for item in dumped.get("findings", []) if item.get("severity") == "review"]
    headline = (
        f"Month-end: {len(errors)} error and {len(reviews)} review items; "
        f"ready: {dumped.get('ready')}."
    )
    sentences = [ExplainSentence(text=headline, finding_ids=[], quotes=[], confidence=1.0)]
    for item in dumped.get("findings", []):
        if item.get("severity") not in ("error", "review"):
            continue
        sentences.append(
            ExplainSentence(
                text=f"[{item.get('severity')}] {item.get('code')}: {item.get('message')}",
                finding_ids=[item.get("id", "")],
                quotes=[item.get("message", "")],
                confidence=1.0,
            )
        )
    _ = summary
    return ExplainDraft(sentences=sentences)


def run_books_explain(
    report: Report,
    *,
    provider: LLMProvider | None,
    allow_pii: bool = False,
    budget_tokens: int | None = None,
    temperature: float = 0.0,
    redactor: Redactor | None = None,
) -> BooksExplainResult:
    """Narrate a recon *report* for the controller, via AI when set.

    ``provider`` None (or over budget, or a failed validation) runs the
    deterministic template with ``source`` template and ``ai_status``
    disabled/fallback.
    """
    variables = recon_variables(report)
    if provider is None:
        return BooksExplainResult(
            source="template",
            model="",
            prompt_version="template",
            prompt_hash="",
            ai_status="disabled",
            sentences=template_narrative(report).sentences,
            usage=AiUsage(status="disabled"),
        )
    template = load_template("books_explain")
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
        fallback=lambda: template_narrative(report),
        redactor=redactor,
    )
    if outcome.ai_status in ("ok", "repaired") and validate_books_explain(variables, outcome.data):
        fallback_draft = template_narrative(report)
        return BooksExplainResult(
            source="template",
            model=outcome.model,
            prompt_version=outcome.prompt_version,
            prompt_hash=outcome.prompt_hash,
            ai_status="fallback",
            sentences=fallback_draft.sentences,
            usage=outcome.usage.model_copy(update={"status": "fallback"}),
        )
    source = "ai" if outcome.ai_status in ("ok", "repaired") else "template"
    return BooksExplainResult(
        source=source,
        model=outcome.model,
        prompt_version=outcome.prompt_version,
        prompt_hash=outcome.prompt_hash,
        ai_status=outcome.ai_status,
        sentences=list(outcome.data.sentences),
        usage=outcome.usage,
    )


def render_books_table(result: BooksExplainResult) -> str:
    """Human-readable sentence list."""
    lines = [f"controller narrative (source: {result.source}, status: {result.ai_status})"]
    for sentence in result.sentences:
        lines.append(f"- {sentence.text}")
    return "\n".join(lines) + "\n"


def render_books_markdown(result: BooksExplainResult) -> str:
    """Markdown sentence list with an AI footer when applicable."""
    lines = ["# Controller narrative", ""]
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


__all__: list[str] = [
    "BooksExplainResult",
    "injection_followed",
    "recon_variables",
    "render_books_markdown",
    "render_books_table",
    "report_money_figures",
    "run_books_explain",
    "template_narrative",
    "validate_books_explain",
]
