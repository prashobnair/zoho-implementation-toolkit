"""Books port tests: exact reconciliation values and TK-FIX-2 row isolation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from zohokit.core.context import RunContext
from zohokit.core.findings import Severity
from zohokit.modules.books.engine import analyze, run
from zohokit.modules.books.models import BooksInput
from zohokit.modules.books.report import to_legacy_dict
from zohokit.reports import render_json

ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _examples() -> BooksInput:
    path = ROOT / "legacy" / "zoho-books-sync-reconciler" / "examples.json"
    return BooksInput.model_validate(json.loads(path.read_text()))


def test_examples_exact_findings() -> None:
    analysis = analyze(_examples())
    assert analysis.ready is False
    assert to_legacy_dict(analysis)["findings"][0] == {
        "deal": "d-2",
        "code": "cross_entity_invoice",
    }
    assert to_legacy_dict(analysis)["deal_count"] == 3
    assert to_legacy_dict(analysis)["invoice_count"] == 3
    assert to_legacy_dict(analysis)["created_invoices"] == 0


def test_clean_pair_ready() -> None:
    inputs = _examples()
    inputs.deals = [inputs.deals[0]]
    inputs.invoices = [inputs.invoices[0]]
    analysis = analyze(inputs)
    assert analysis.ready is True
    assert to_legacy_dict(analysis)["findings"] == []


def _two_deal_input() -> BooksInput:
    return BooksInput(
        entities={"fictional-india": "INR"},
        deals=[
            {"id": "d-1", "entity": "fictional-india", "currency": "INR", "net_amount": "1200.00"},
            {"id": "d-2", "entity": "fictional-india", "currency": "INR", "net_amount": "12.34.56"},
        ],
        invoices=[
            {
                "id": "i-1",
                "deal_ref": "d-1",
                "entity": "fictional-india",
                "currency": "INR",
                "net_amount": "1200.00",
                "tax_reviewed": True,
                "sync_state": "ok",
            },
            {
                "id": "i-2",
                "deal_ref": "d-2",
                "entity": "fictional-india",
                "currency": "INR",
                "net_amount": "500.00",
                "tax_reviewed": True,
                "sync_state": "ok",
            },
        ],
    )


def test_bad_deal_amount_isolated_tk_fix_2() -> None:
    """One malformed amount: invalid_amount on d-2, run continues, ready false."""
    analysis = analyze(_two_deal_input())
    legacy = to_legacy_dict(analysis)
    assert legacy["findings"] == [{"deal": "d-2", "code": "invalid_amount"}]
    assert legacy["ready_for_sync"] is False
    assert analysis.ready is False
    (finding,) = analysis.findings
    assert finding.code == "invalid_amount"
    assert finding.severity is Severity.ERROR
    assert finding.entity_id == "d-2"
    assert finding.evidence == {"row": "deal", "value": "12.34.56"}


def test_bad_invoice_amount_skips_only_its_comparison() -> None:
    inputs = _two_deal_input()
    inputs.deals[1]["net_amount"] = "75.00"
    inputs.invoices[1]["net_amount"] = "abc"
    analysis = analyze(inputs)
    assert to_legacy_dict(analysis)["findings"] == [{"deal": "d-2", "code": "invalid_amount"}]
    (finding,) = [item for item in analysis.findings if item.code == "invalid_amount"]
    assert finding.evidence == {"row": "invoice", "value": "abc"}


def test_non_string_amount_is_invalid() -> None:
    inputs = _two_deal_input()
    inputs.deals[1]["net_amount"] = 75
    analysis = analyze(inputs)
    assert to_legacy_dict(analysis)["findings"] == [{"deal": "d-2", "code": "invalid_amount"}]


def test_frozen_clock_byte_identical() -> None:
    inputs = _examples()
    now = datetime(2026, 9, 27, 12, tzinfo=UTC)
    assert render_json(run(inputs, ctx=RunContext(now=now))) == render_json(
        run(inputs, ctx=RunContext(now=now))
    )
