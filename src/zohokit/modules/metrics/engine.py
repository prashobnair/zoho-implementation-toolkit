"""Metrics contracts engine (TK-MIG-3).

Port of ``legacy/zoho-analytics-metrics-contracts/metrics.py`` with two
intentional fixes: duplicate deal/invoice IDs record ``duplicate_id`` and
are excluded from aggregates with an ``excluded_rows`` count (TK-FIX-3);
staff rows are validated per row, else ``invalid_staff_row`` (TK-FIX-4).
Timestamps go through core ``time.parse``.
"""

from __future__ import annotations

import copy
import hashlib
from decimal import Decimal, InvalidOperation
from typing import Any

from zohokit.core.context import RunContext
from zohokit.core.findings import Finding, Report, Severity
from zohokit.core.ids import canonical_json
from zohokit.core.time import InvalidTimeError
from zohokit.core.time import parse as parse_time
from zohokit.modules import Analysis
from zohokit.modules.metrics.models import MetricsInput
from zohokit.modules.metrics.report import build_report

AUDIENCES = {"sales", "finance", "operations"}


def _instant(value: Any) -> Any:
    if not isinstance(value, str):
        raise ValueError("Invalid timestamp")
    try:
        return parse_time(value)
    except InvalidTimeError as exc:
        raise ValueError(str(exc)) from exc


def _hours(value: Any) -> Decimal | None:
    """Parse staff hours; None when the row fails TK-FIX-4 validation."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def analyze(inputs: MetricsInput, *, audience: str = "finance") -> Analysis:
    """Evaluate metric contracts; return findings plus the legacy dict."""
    data = copy.deepcopy(inputs.model_dump())
    if not isinstance(data, dict) or audience not in AUDIENCES:
        raise ValueError("Expected data and audience sales/finance/operations")
    for key in ("accounts", "deals", "invoices", "staff"):
        if not isinstance(data.get(key), list):
            raise ValueError(f"{key} must be list")
    as_of = _instant(data.get("as_of"))
    accounts: dict[Any, Any] = {}
    for row in data["accounts"]:
        key = row.get("id")
        if not key or key in accounts:
            raise ValueError("Account IDs must be unique")
        accounts[key] = row
    findings: list[dict[str, Any]] = []
    new_findings: list[Finding] = []
    position = 0
    excluded_rows = 0

    def record(code: str, source: Any, extra: dict[str, Any] | None = None) -> None:
        nonlocal position
        entry = {"code": code, "source": source}
        findings.append(entry)
        evidence: dict[str, Any] = {"legacy_finding": entry}
        if extra:
            evidence.update(extra)
        new_findings.append(
            Finding.create(
                module="metrics",
                code=code,
                severity=Severity.ERROR,
                entity="source",
                entity_id=str(source),
                message=f"{code}: {source}",
                evidence=evidence,
                discriminator=str(position),
            )
        )
        position += 1

    for name in ("crm", "books", "people"):
        updated = _instant((data.get("updated_at") or {}).get(name))
        if updated > as_of:
            record("future_snapshot", name)
        elif (as_of - updated).total_seconds() > 86400:
            record("stale_snapshot", name)
    deal_count = 0
    won_accounts: set[Any] = set()
    seen_deals: set[str] = set()
    for deal in data["deals"]:
        deal_id = str(deal.get("id", ""))
        if deal_id and deal_id in seen_deals:
            excluded_rows += 1
            record("duplicate_id", deal_id, {"excluded_rows": excluded_rows})
            continue
        if deal_id:
            seen_deals.add(deal_id)
        account = deal.get("account_id")
        if account not in accounts:
            record("orphan_deal", str(deal.get("id", "")))
            continue
        if deal.get("stage") == "won":
            deal_count += 1
            won_accounts.add(account)
    revenue = Decimal("0")
    seen_invoices: set[str] = set()
    for invoice in data["invoices"]:
        invoice_id = str(invoice.get("id", ""))
        if invoice_id and invoice_id in seen_invoices:
            excluded_rows += 1
            record("duplicate_id", invoice_id, {"excluded_rows": excluded_rows})
            continue
        if invoice_id:
            seen_invoices.add(invoice_id)
        if invoice.get("account_id") not in accounts:
            record("orphan_invoice", str(invoice.get("id", "")))
            continue
        try:
            value = Decimal(str(invoice["net_amount"]))
        except (KeyError, InvalidOperation) as exc:
            raise ValueError("Invalid invoice amount") from exc
        if not value.is_finite() or value < 0:
            raise ValueError("Invalid invoice amount")
        if invoice.get("currency") != data.get("currency"):
            record("currency_mismatch", str(invoice.get("id", "")))
            continue
        if invoice.get("status") == "paid":
            revenue += value
    valid_staff: list[tuple[Decimal, Decimal]] = []
    for row in data["staff"]:
        available = _hours(row.get("hours_available", 0))
        booked = _hours(row.get("hours_booked", 0))
        if (
            available is None
            or booked is None
            or available <= 0
            or booked < 0
            or booked > available
        ):
            record(
                "invalid_staff_row",
                str(row.get("id", "")),
                {"row": {key: row.get(key) for key in ("hours_available", "hours_booked")}},
            )
            continue
        valid_staff.append((available, booked))
    utilization = None
    if data["staff"]:
        total = sum(available for available, _ in valid_staff)
        used = sum(booked for _, booked in valid_staff)
        if total <= 0 or used < 0 or used > total:
            record("invalid_utilization", "people")
        else:
            utilization = str((used / total * 100).quantize(Decimal("0.01")))
    metrics: dict[str, Any] = {"won_deals": deal_count, "won_accounts": len(won_accounts)}
    if audience == "finance":
        metrics["paid_net_revenue"] = str(revenue)
        metrics["currency"] = data.get("currency")
    if audience == "operations":
        metrics["booked_utilization_percent"] = utilization
    ready = not findings
    legacy = {
        "audience": audience,
        "metrics": metrics,
        "findings": findings,
        "as_of": as_of.isoformat(),
        "dashboard": False,
    }
    return Analysis(findings=tuple(new_findings), legacy=legacy, ready=ready)


def run(inputs: MetricsInput, *, ctx: RunContext, audience: str = "finance") -> Report:
    """Evaluate the contracts: ``run(inputs, *, ctx) -> Report`` (TK-ARCH-1)."""
    analysis = analyze(inputs, audience=audience)
    digest = hashlib.sha256(
        canonical_json({**inputs.model_dump(mode="json"), "audience": audience}).encode("utf-8")
    ).hexdigest()
    return build_report(analysis, ctx=ctx, inputs_sha256=digest)


__all__: list[str] = ["analyze", "run"]
