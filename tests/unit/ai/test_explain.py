"""Explain tests (TK-CORE-9): template, audiences, AI validation, renderers."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from zohokit.ai.explain import (
    ExplainResult,
    explain_variables,
    filter_for_audience,
    render_explain_html,
    render_explain_markdown,
    render_explain_table,
    run_explain,
    template_summary,
    validate_explain_draft,
)
from zohokit.ai.prompts import load_template
from zohokit.ai.providers import FakeProvider
from zohokit.ai.redaction import build_prompt
from zohokit.ai.schemas import ExplainDraft
from zohokit.core.findings import Finding, Report, ReportSummary
from zohokit.core.redact import Redactor


def _report() -> Report:
    now = datetime(2026, 10, 6, tzinfo=UTC)
    return Report(
        module="migration",
        run_id="run-1",
        started_at=now,
        finished_at=now,
        mode="offline",
        inputs_sha256="abc123",
        ready=False,
        summary=ReportSummary(error=1, review=1, warning=0, info=0),
        findings=[
            Finding.create(
                module="migration",
                code="orphan_person",
                severity="error",
                entity="deals",
                entity_id="d-2",
                message="Deal D-1042 references person P-9007 who is missing.",
                evidence={"person_id": "p-9", "email": "missing.two@example.invalid"},
                remediation="Add the person to the export.",
            ),
            Finding.create(
                module="migration",
                code="owner_unmapped",
                severity="review",
                entity="people",
                entity_id="p-3",
                message="4 leads have no matching Zoho user.",
                remediation="Map owners before import.",
            ),
        ],
        artifacts={"html": "reports/out.html"},
    )


def test_template_summary_cites_every_finding() -> None:
    filtered = filter_for_audience(_report(), "internal")
    draft = template_summary(filtered)
    assert len(draft.sentences) == 3
    assert draft.sentences[0].finding_ids == []
    assert draft.sentences[1].finding_ids == [filtered["findings"][0]["id"]]
    assert all(item.confidence == 1.0 for item in draft.sentences)


def test_client_audience_drops_internal_only_fields() -> None:
    filtered = filter_for_audience(_report(), "client")
    assert set(filtered) == {"ready", "summary", "findings"}
    assert all(
        set(item) == {"id", "code", "severity", "message", "remediation"}
        for item in filtered["findings"]
    )
    dumped = json.dumps(filtered)
    assert "run-1" not in dumped
    assert "abc123" not in dumped
    assert "reports/out.html" not in dumped
    assert "missing.two@example.invalid" not in dumped
    assert "p-9" not in dumped


def test_internal_audience_keeps_messages() -> None:
    filtered = filter_for_audience(_report(), "internal")
    assert "D-1042" in filtered["findings"][0]["message"]


def test_run_explain_without_provider_is_disabled() -> None:
    result = run_explain(_report(), "internal", provider=None)
    assert result.ai_status == "disabled"
    assert result.source == "ai"
    assert result.prompt_version == "template"
    assert len(result.sentences) == 3
    assert result.usage.status == "disabled"


def _good_response(report: Report) -> tuple[FakeProvider, dict[str, str]]:
    filtered = filter_for_audience(report, "internal")
    variables = explain_variables(filtered, "internal")
    prompt = build_prompt(load_template("explain"), variables, redactor=Redactor())
    first, second = filtered["findings"]
    raw = json.dumps(
        {
            "sentences": [
                {
                    "text": first["message"],
                    "finding_ids": [first["id"]],
                    "quotes": [first["message"]],
                    "confidence": 0.95,
                },
                {
                    "text": second["message"],
                    "finding_ids": [second["id"]],
                    "quotes": [second["message"]],
                    "confidence": 0.9,
                },
            ]
        }
    )
    return FakeProvider({prompt.prompt_hash: raw}, model="test-fake"), variables


def test_run_explain_ai_path_validates_and_labels() -> None:
    report = _report()
    provider, _ = _good_response(report)
    result = run_explain(report, "internal", provider=provider)
    assert result.ai_status == "ok"
    assert result.source == "ai"
    assert result.model == "test-fake"
    assert result.prompt_version == "v1"
    assert result.prompt_hash
    assert len(result.sentences) == 2
    assert result.usage.prompt_hash == result.prompt_hash
    assert result.usage.status == "ok"


def test_run_explain_ai_bad_citation_falls_back() -> None:
    report = _report()
    filtered = filter_for_audience(report, "internal")
    variables = explain_variables(filtered, "internal")
    prompt = build_prompt(load_template("explain"), variables, redactor=Redactor())
    raw = json.dumps(
        {
            "sentences": [
                {
                    "text": "invented",
                    "finding_ids": ["ffffffffffffffffffffffff"],
                    "quotes": ["invented"],
                    "confidence": 0.9,
                }
            ]
        }
    )
    provider = FakeProvider({prompt.prompt_hash: raw}, model="test-fake")
    result = run_explain(report, "internal", provider=provider)
    assert result.ai_status == "fallback"
    assert len(result.sentences) == 3


def test_run_explain_ai_hallucinated_number_falls_back() -> None:
    report = _report()
    filtered = filter_for_audience(report, "internal")
    variables = explain_variables(filtered, "internal")
    prompt = build_prompt(load_template("explain"), variables, redactor=Redactor())
    first = filtered["findings"][0]
    raw = json.dumps(
        {
            "sentences": [
                {
                    "text": "99 more deals are missing",
                    "finding_ids": [first["id"]],
                    "quotes": [first["message"]],
                    "confidence": 0.9,
                }
            ]
        }
    )
    provider = FakeProvider({prompt.prompt_hash: raw}, model="test-fake")
    result = run_explain(report, "internal", provider=provider)
    assert result.ai_status == "fallback"


def test_validate_explain_draft_value_free() -> None:
    report = _report()
    variables = explain_variables(filter_for_audience(report, "internal"), "internal")
    draft = ExplainDraft.model_validate({"sentences": []})
    assert validate_explain_draft(variables, draft) == []


def test_renderers_mark_ai_items() -> None:
    report = _report()
    provider, _ = _good_response(report)
    result = run_explain(report, "internal", provider=provider)
    assert isinstance(result, ExplainResult)
    assert "AI suggestion" in render_explain_markdown(result)
    html = render_explain_html(result)
    assert "AI suggestion" in html
    assert "0.95" in html
    assert "<li>" in html
    table = render_explain_table(result)
    assert table.startswith("audience: internal")


def test_template_html_carries_no_badge() -> None:
    result = run_explain(_report(), "client", provider=None)
    assert "AI suggestion" not in render_explain_html(result)
    assert "Template summary" in render_explain_markdown(result)
