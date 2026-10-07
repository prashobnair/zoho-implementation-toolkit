"""Controller-narrative tests (AI-BK-1): money grounding, omission, CLI."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from zohokit.ai.schemas import ExplainDraft, ExplainSentence
from zohokit.ai.validators import (
    MoneyFigure as _MoneyFigure,
)
from zohokit.ai.validators import (
    check_money_grounded,
    extract_money_figures,
    strip_money_figures,
)
from zohokit.core.context import RunContext
from zohokit.modules.books.entities import load_entity_map
from zohokit.modules.books.explain import (
    recon_variables,
    report_money_figures,
    run_books_explain,
    template_narrative,
    validate_books_explain,
)
from zohokit.modules.books.fx import load_fx_rates
from zohokit.modules.books.policy import load_policy
from zohokit.modules.books.reconcile import run_recon

ROOT = Path(__file__).resolve().parent.parent.parent.parent
MARIGOLD = ROOT / "fixtures" / "books" / "marigold"
ORG_IDS = {"in-entity": "555000001", "us-entity": "555000002", "eu-entity": "555000003"}


def _report():  # type: ignore[no-untyped-def]
    data = json.loads((MARIGOLD / "recon.json").read_text(encoding="utf-8"))
    return run_recon(
        data,
        policy=load_policy(MARIGOLD / "policy.yaml"),
        entities=load_entity_map(MARIGOLD / "entity_map.yaml"),
        org_ids=ORG_IDS,
        fx_rates=load_fx_rates(MARIGOLD / "fx_rates.csv"),
        unavailable=("eu-entity",),
        ctx=RunContext(now=datetime(2026, 10, 1, tzinfo=UTC), mode="offline"),
    )


def test_money_figures_parse_indian_notation() -> None:
    figures, _ = extract_money_figures(
        "3 deals (₹4.2L) missing; 1.5 Cr over cap; $1.2k fees; 1.2M total"
    )
    by_value = sorted(figure.value for figure in figures)
    assert by_value == [
        Decimal("1200"),
        Decimal("420000"),
        Decimal("1200000"),
        Decimal("15000000"),
    ]
    lakh, _ = extract_money_figures("4.2 lakh outstanding")
    assert [figure.value for figure in lakh] == [Decimal("420000")]
    crore, _ = extract_money_figures("1.5 crore booked")
    assert [figure.value for figure in crore] == [Decimal("15000000")]


def test_money_precision_accepts_rounding_rejects_overprecision() -> None:
    allowed = [_MoneyFigure(value=Decimal("421234"), precision=Decimal("0.01"))]
    assert check_money_grounded(narrative="booked ₹4.2L", allowed=allowed).ok is True
    assert check_money_grounded(narrative="booked ₹4.20L", allowed=allowed).ok is False
    assert check_money_grounded(narrative="booked ₹4.3L", allowed=allowed).ok is False


def test_strip_money_figures_blanks_spans() -> None:
    stripped = strip_money_figures("Deal d-1 matched at ₹4.2L on 2026-09-15.")
    assert "4.2" not in stripped
    assert "2026-09-15" in stripped


def test_no_provider_means_template_disabled() -> None:
    result = run_books_explain(_report(), provider=None)
    assert result.source == "template"
    assert result.ai_status == "disabled"
    assert result.sentences


def test_template_narrative_cites_every_error() -> None:
    report = _report()
    variables = recon_variables(report)
    draft = template_narrative(report)
    assert validate_books_explain(variables, draft) == []


def test_report_amounts_feed_money_figures() -> None:
    variables = recon_variables(_report())
    values = {figure.value for figure in report_money_figures(variables)}
    assert Decimal("420000.00") in values
    assert Decimal("88410.00") in values


def test_valid_ai_narrative_passes() -> None:
    from zohokit.ai.pipeline import AiRequest, run_ai
    from zohokit.ai.prompts import load_template
    from zohokit.ai.providers import FakeProvider
    from zohokit.ai.redaction import build_prompt
    from zohokit.core.redact import Redactor

    report = _report()
    variables = recon_variables(report)
    error_items = [item for item in report.findings if str(item.severity) == "error"]
    sentences = []
    for item in error_items:
        dumped = item.model_dump(mode="json")
        net = (dumped.get("evidence") or {}).get("deal_net", "")
        figure = f"₹{net}" if net else ""
        text = f"{dumped['entity']}:{dumped['entity_id']} needs review"
        if figure:
            text += f" at {figure}"
        text += "."
        sentences.append(
            ExplainSentence(
                text=text,
                finding_ids=[dumped["id"]],
                quotes=[dumped["message"]],
                confidence=0.9,
            )
        )
    template = load_template("books_explain")
    prompt = build_prompt(template, variables, redactor=Redactor())
    raw = ExplainDraft(sentences=sentences).model_dump_json()
    provider = FakeProvider({prompt.prompt_hash: raw}, model="test-fake")
    outcome = run_ai(
        provider,
        AiRequest(template=template, variables=variables),
        ExplainDraft,
        fallback=ExplainDraft,
    )
    assert outcome.ai_status == "ok"
    assert validate_books_explain(variables, outcome.data) == []
    result = run_books_explain(report, provider=provider)
    assert result.source == "ai"


def test_hallucinated_lakh_falls_back() -> None:
    from zohokit.ai.prompts import load_template
    from zohokit.ai.providers import FakeProvider
    from zohokit.ai.redaction import build_prompt
    from zohokit.core.redact import Redactor

    report = _report()
    variables = recon_variables(report)
    error_items = [item for item in report.findings if str(item.severity) == "error"]
    dumped = error_items[0].model_dump(mode="json")
    bad = ExplainDraft(
        sentences=[
            ExplainSentence(
                text="deal:d-in-01 needs review at ₹4.9L.",
                finding_ids=[dumped["id"]],
                quotes=[dumped["message"]],
                confidence=0.9,
            )
        ]
    )
    template = load_template("books_explain")
    prompt = build_prompt(template, variables, redactor=Redactor())
    provider = FakeProvider({prompt.prompt_hash: bad.model_dump_json()}, model="test-fake")
    result = run_books_explain(report, provider=provider)
    assert result.ai_status == "fallback"
    assert result.source == "template"


def test_cli_books_explain_template_and_disabled(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from zohokit.cli import app

    report_path = tmp_path / "report.json"
    report_path.write_text(_report().model_dump_json(indent=2), encoding="utf-8")
    table = CliRunner().invoke(app, ["books", "explain", str(report_path), "--format", "table"])
    assert table.exit_code == 0, table.output
    assert "controller narrative" in table.output.lower()
    plain = CliRunner().invoke(app, ["books", "explain", str(report_path)])
    assert plain.exit_code == 0, plain.output
    payload = json.loads(plain.output)
    assert payload["source"] == "template"
    ai = CliRunner().invoke(app, ["books", "explain", str(report_path), "--ai"])
    assert ai.exit_code == 0, ai.output
    assert "AI disabled" in ai.output
    assert json.loads(ai.output[ai.output.index("{") :])["ai_status"] == "disabled"
