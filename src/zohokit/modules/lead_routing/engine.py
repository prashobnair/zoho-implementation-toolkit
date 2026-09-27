"""Lead routing engine (TK-MIG-3).

Port of ``legacy/zoho-lead-routing-lab/routing.py``. Phone handling goes
through core ``phones.py``: without an explicit ``default_region`` there is
no region guessing (legacy parity); with one, inferred numbers carry the
``inferred_region`` flag and route normally.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import asdict, dataclass
from typing import Any

from zohokit.core.context import RunContext
from zohokit.core.findings import Finding, Report, Severity
from zohokit.core.ids import canonical_json
from zohokit.core.phones import PhoneError
from zohokit.core.phones import parse as parse_phone
from zohokit.modules import Analysis
from zohokit.modules.lead_routing.models import LeadRoutingInput
from zohokit.modules.lead_routing.report import build_report

CHANNELS = {"whatsapp", "instagram", "forms"}

_STATUS_SEVERITY = {"qualified": Severity.INFO, "review": Severity.REVIEW, "duplicate": Severity.REVIEW}


@dataclass(frozen=True)
class Decision:
    lead_id: str
    status: str
    route: str | None
    reason: str
    phone: str | None
    duplicate_of: str | None = None


def normalize_phone(raw: Any, *, default_region: str | None = None) -> str | None:
    """Normalize to E.164 via core phones; None when unusable.

    Without an explicit ``default_region`` a number with no country code is
    rejected, never guessed — the legacy behavior.
    """
    if not isinstance(raw, str):
        return None
    try:
        return parse_phone(raw, default_region=default_region).e164
    except PhoneError:
        return None


def _normalize_detail(raw: Any, *, default_region: str | None = None) -> tuple[str | None, bool]:
    if not isinstance(raw, str):
        return None, False
    try:
        parsed = parse_phone(raw, default_region=default_region)
    except PhoneError:
        return None, False
    return parsed.e164, parsed.inferred_region


def analyze(inputs: LeadRoutingInput, *, default_region: str | None = None) -> Analysis:
    """Route the leads; return findings plus the legacy result dict."""
    leads = copy.deepcopy(inputs.leads)
    if not isinstance(leads, list):
        raise ValueError("leads must be a list")
    seen_ids: set[str] = set()
    seen_phones: dict[str, str] = {}
    decisions: list[Decision] = []
    new_findings: list[Finding] = []
    position = 0
    for item in leads:
        if not isinstance(item, dict):
            raise ValueError("Each lead must be an object")
        lead_id = str(item.get("id", "")).strip()
        if not lead_id or lead_id in seen_ids:
            raise ValueError("Lead IDs must be unique and nonempty")
        seen_ids.add(lead_id)
        channel = item.get("channel")
        phone, inferred = _normalize_detail(item.get("phone"), default_region=default_region)
        if channel not in CHANNELS:
            decisions.append(Decision(lead_id, "review", "human_queue", "unsupported_channel", phone))
        elif not phone:
            decisions.append(Decision(lead_id, "review", "human_queue", "invalid_or_missing_e164", None))
        elif phone in seen_phones:
            decisions.append(
                Decision(lead_id, "duplicate", None, "phone_candidate_match", phone, seen_phones[phone])
            )
        else:
            # Reserve the valid phone even when later qualification needs review.
            seen_phones[phone] = lead_id
            if item.get("consent") is not True:
                decisions.append(Decision(lead_id, "review", "human_queue", "consent_not_verified", phone))
            elif item.get("intent") == "sales" and item.get("budget_confirmed") is True:
                decisions.append(
                    Decision(lead_id, "qualified", "sales_queue", "qualified_sales_inquiry", phone)
                )
            elif item.get("intent") in {"support", "unknown"}:
                decisions.append(Decision(lead_id, "review", "human_queue", "needs_human_triage", phone))
            elif item.get("intent") == "sales":
                decisions.append(Decision(lead_id, "review", "human_queue", "budget_unconfirmed", phone))
            else:
                decisions.append(Decision(lead_id, "review", "human_queue", "unrecognized_intent", phone))
        if inferred and phone is not None:
            new_findings.append(
                Finding.create(
                    module="lead_routing",
                    code="inferred_region",
                    severity=Severity.INFO,
                    entity="lead",
                    entity_id=lead_id,
                    message=f"Region for {lead_id} was inferred from the explicit default.",
                    evidence={"default_region": default_region},
                    discriminator=str(position),
                )
            )
            position += 1
    created = tuple(
        Finding.create(
            module="lead_routing",
            code=decision.reason,
            severity=_STATUS_SEVERITY[decision.status],
            entity="lead",
            entity_id=decision.lead_id,
            message=f"{decision.reason}: {decision.lead_id}",
            evidence={"legacy_decision": asdict(decision)},
            discriminator=str(position + index),
        )
        for index, decision in enumerate(decisions)
    )
    all_findings = tuple(sorted(new_findings + list(created), key=lambda f: (f.entity_id, f.code)))
    counts = {
        name: sum(decision.status == name for decision in decisions)
        for name in ("qualified", "review", "duplicate")
    }
    ready = counts["review"] == 0 and counts["duplicate"] == 0
    legacy = {
        "mode": "simulation_only",
        "decisions": [asdict(decision) for decision in decisions],
        "counts": counts,
        "outbound_messages": 0,
    }
    return Analysis(findings=all_findings, legacy=legacy, ready=ready)


def run(inputs: LeadRoutingInput, *, ctx: RunContext, default_region: str | None = None) -> Report:
    """Route the leads: ``run(inputs, *, ctx) -> Report`` (TK-ARCH-1)."""
    analysis = analyze(inputs, default_region=default_region)
    digest = hashlib.sha256(
        canonical_json(
            {**inputs.model_dump(mode="json"), "default_region": default_region}
        ).encode("utf-8")
    ).hexdigest()
    return build_report(analysis, ctx=ctx, inputs_sha256=digest)


__all__: list[str] = ["analyze", "normalize_phone", "run"]
