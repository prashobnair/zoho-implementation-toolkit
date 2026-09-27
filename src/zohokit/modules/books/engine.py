"""Books reconciliation engine (TK-MIG-3).

Port of ``legacy/zoho-books-sync-reconciler/reconcile.py`` with one
intentional fix (TK-FIX-2): a malformed amount records an ``invalid_amount``
error finding on that row and skips its amount comparisons instead of
aborting the whole run. Amounts go through core ``money.parse`` (strict).
"""

from __future__ import annotations

import copy
import hashlib
from collections import defaultdict
from decimal import Decimal
from typing import Any

from zohokit.core.context import RunContext
from zohokit.core.findings import Finding, Report, Severity
from zohokit.core.ids import canonical_json
from zohokit.core.money import MoneyError
from zohokit.core.money import parse as parse_amount
from zohokit.modules import Analysis
from zohokit.modules.books.models import BooksInput
from zohokit.modules.books.report import build_report


def _parse_row_amount(value: Any) -> Decimal:
    """Strict amount parsing: strings only, via core money.parse."""
    if not isinstance(value, str):
        raise MoneyError(f"amount must be a decimal string, got {value!r}")
    return parse_amount(value)


def analyze(inputs: BooksInput) -> Analysis:
    """Reconcile deals vs invoices; return findings plus the legacy dict."""
    data = copy.deepcopy(inputs.model_dump())
    if not isinstance(data, dict) or any(
        not isinstance(data.get(key), list) for key in ("deals", "invoices")
    ):
        raise ValueError("deals and invoices must be lists")
    entities = data.get("entities")
    if not isinstance(entities, dict):
        raise ValueError("entities must be an object")
    findings: list[dict[str, Any]] = []
    invoices_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    deals_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for inv in data["invoices"]:
        if not isinstance(inv, dict):
            raise ValueError("invoice must be an object")
        key = str(inv.get("deal_ref", ""))
        invoices_by_key[key].append(inv)
    for deal in data["deals"]:
        if not isinstance(deal, dict):
            raise ValueError("deal must be an object")
        key = str(deal.get("id", ""))
        deals_by_key[key].append(deal)
    new_findings: list[Finding] = []
    position = 0

    def record(code: str, deal: str, evidence: dict[str, Any]) -> None:
        nonlocal position
        findings.append({"deal": deal, "code": code})
        new_findings.append(
            Finding.create(
                module="books",
                code=code,
                severity=Severity.ERROR,
                entity="deal",
                entity_id=deal,
                message=f"{code} on deal {deal or '<missing>'}",
                evidence=evidence,
                discriminator=str(position),
            )
        )
        position += 1

    for key, rows in sorted(deals_by_key.items()):
        if not key or len(rows) != 1:
            record("duplicate_or_missing_deal_id", key, {"legacy_finding": {"deal": key}})
            continue
        deal = rows[0]
        tenant = str(deal.get("entity", ""))
        currency = str(deal.get("currency", ""))
        if tenant not in entities or currency != entities.get(tenant):
            record("entity_currency_mismatch", key, {"legacy_finding": {"deal": key}})
        try:
            expected: Decimal | None = _parse_row_amount(deal.get("net_amount"))
        except MoneyError:
            record(
                "invalid_amount",
                key,
                {"row": "deal", "value": deal.get("net_amount")},
            )
            expected = None
        matches = invoices_by_key.get(key, [])
        if not matches:
            record("missing_invoice", key, {"legacy_finding": {"deal": key}})
        if len(matches) > 1:
            record("duplicate_invoice_reference", key, {"legacy_finding": {"deal": key}})
        for inv in matches:
            if str(inv.get("entity", "")) != tenant:
                record("cross_entity_invoice", key, {"legacy_finding": {"deal": key}})
            if str(inv.get("currency", "")) != currency:
                record("currency_mismatch", key, {"legacy_finding": {"deal": key}})
            try:
                actual: Decimal | None = _parse_row_amount(inv.get("net_amount"))
            except MoneyError:
                record(
                    "invalid_amount",
                    key,
                    {"row": "invoice", "value": inv.get("net_amount")},
                )
                actual = None
            if expected is not None and actual is not None and actual != expected:
                record("net_amount_mismatch", key, {"legacy_finding": {"deal": key}})
            if inv.get("tax_reviewed") is not True:
                record("tax_not_reviewed", key, {"legacy_finding": {"deal": key}})
            if inv.get("sync_state") == "failed":
                record("sync_failed", key, {"legacy_finding": {"deal": key}})
    for key in sorted(invoices_by_key):
        if key not in deals_by_key:
            record("orphan_invoice_reference", key, {"legacy_finding": {"deal": key}})
    findings.sort(key=lambda item: (item["deal"], item["code"]))
    new_findings.sort(key=lambda finding: (finding.entity_id, finding.code))
    ready = not findings
    legacy = {
        "mode": "dry_run_only",
        "ready_for_sync": ready,
        "deal_count": len(data["deals"]),
        "invoice_count": len(data["invoices"]),
        "findings": findings,
        "created_invoices": 0,
    }
    return Analysis(findings=tuple(new_findings), legacy=legacy, ready=ready)


def run(inputs: BooksInput, *, ctx: RunContext) -> Report:
    """Run the reconciliation: ``run(inputs, *, ctx) -> Report`` (TK-ARCH-1)."""
    analysis = analyze(inputs)
    digest = hashlib.sha256(
        canonical_json(inputs.model_dump(mode="json")).encode("utf-8")
    ).hexdigest()
    return build_report(analysis, ctx=ctx, inputs_sha256=digest)


__all__: list[str] = ["analyze", "run"]
