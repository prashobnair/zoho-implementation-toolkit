"""Lead routing port tests: core phones, explicit region, exact decisions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from zohokit.core.context import RunContext
from zohokit.core.findings import Severity
from zohokit.modules.lead_routing.engine import analyze, normalize_phone, run
from zohokit.modules.lead_routing.models import LeadRoutingInput
from zohokit.modules.lead_routing.report import to_legacy_dict
from zohokit.reports import render_json

ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _examples() -> LeadRoutingInput:
    path = ROOT / "legacy" / "zoho-lead-routing-lab" / "examples.json"
    return LeadRoutingInput.model_validate(json.loads(path.read_text()))


def test_normalize_phone_exact_legacy_vectors() -> None:
    assert normalize_phone("+91 (900) 000-0001") == "+919000000001"
    for bad in ("9000000001", "00449000000001", "+0123456789", "hi", None):
        assert normalize_phone(bad) is None


def test_explicit_region_parses_local() -> None:
    assert normalize_phone("9000000002", default_region="IN") == "+919000000002"
    assert normalize_phone("9000000002") is None


def test_examples_exact_decisions() -> None:
    analysis = analyze(_examples())
    legacy = to_legacy_dict(analysis)
    assert legacy["counts"] == {"qualified": 1, "review": 3, "duplicate": 1}
    assert legacy["decisions"][1]["duplicate_of"] == "lead-1"
    assert legacy["outbound_messages"] == 0
    assert analysis.ready is False


def test_region_in_routes_support_lead() -> None:
    inputs = LeadRoutingInput(
        leads=[
            {
                "id": "lead-9",
                "channel": "forms",
                "phone": "9000000002",
                "consent": True,
                "intent": "support",
            }
        ]
    )
    analysis = analyze(inputs, default_region="IN")
    legacy = to_legacy_dict(analysis)
    assert legacy["decisions"][0]["route"] == "human_queue"
    assert legacy["decisions"][0]["reason"] == "needs_human_triage"
    assert legacy["decisions"][0]["phone"] == "+919000000002"
    (inferred,) = [item for item in analysis.findings if item.code == "inferred_region"]
    assert inferred.severity is Severity.INFO
    assert inferred.entity_id == "lead-9"


def test_consent_blocks_qualification() -> None:
    inputs = LeadRoutingInput(
        leads=[
            {
                "id": "new",
                "channel": "whatsapp",
                "phone": "+919999999999",
                "consent": False,
                "intent": "sales",
                "budget_confirmed": True,
            }
        ]
    )
    analysis = analyze(inputs)
    assert to_legacy_dict(analysis)["decisions"][0]["reason"] == "consent_not_verified"


def test_frozen_clock_byte_identical() -> None:
    inputs = _examples()
    now = datetime(2026, 9, 27, 12, tzinfo=UTC)
    assert render_json(run(inputs, ctx=RunContext(now=now))) == render_json(
        run(inputs, ctx=RunContext(now=now))
    )
