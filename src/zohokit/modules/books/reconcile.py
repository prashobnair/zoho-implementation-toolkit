"""Books month-end reconciliation v2 (TK-BK-F1..F6, TK-BK-F8, UC-BK-1..3).

The legacy exact-match engine (:mod:`engine`) is untouched — parity
goldens still run through it. This engine adds the month-end workbench:

- key strategies from the match policy (deal id in an invoice custom
  field, ``reference_number``, ``sales_order_link``);
- absolute + percentage tolerance (``within_tolerance`` info vs
  ``outside_tolerance`` / ``under_invoiced`` / ``over_invoiced``);
- staged billing: a deal carrying the billing-plan field may be covered
  by several invoices that must sum to the deal net (UC-BK-2);
- credit notes netted off the invoiced total (``net_off``);
- net-only vs gross-with-tax-table comparison;
- multi-org entity maps with fingerprint-only org references (UC-BK-3:
  an invoice in the wrong legal entity is never matched by customer
  name — it is flagged ``cross_entity_invoice`` with both fingerprints);
- an exact-match FX table (missing rate → ``fx_rate_missing``);
- draft/void status handling (drafts excluded by default);
- period windowing with documented inclusive bounds (the chosen dimension
  filters its own records: ``deal_closing_date`` windows deals, leaving
  invoices unfiltered; ``invoice_date`` windows invoices, leaving deals
  unfiltered);
- row-level ``invalid_amount`` without aborting, and per-org
  ``source_unavailable`` while the other orgs continue.

Finding identity (TK-CORE-2): ``entity_id`` is always a stable source id
(deal id, invoice id, credit-note id, entity key) — never a position or
count — with the discriminator naming the contributing source row(s).

Finding semantics for amount verdicts:

- one matched invoice: ``within_tolerance`` (info) when the difference
  is inside both tolerance bounds, else ``outside_tolerance`` (error);
- several matched invoices with the billing-plan field set: the invoices
  must sum to the deal net — ``within_tolerance`` (info) on success,
  ``under_invoiced`` / ``over_invoiced`` (error) on a shortfall/excess;
- several matched invoices without the field: ``duplicate_invoice_reference``
  (error), no amount verdict;
- no matched invoice: ``missing_invoice`` (error);
- an invoice whose key matches no deal of its own entity:
  ``orphan_invoice_reference`` (error, entity ``invoice``);
- an invoice key-matched to a deal in another legal entity, or a stray
  invoice sharing a customer name across entities: ``cross_entity_invoice``
  (error) — on the deal for a key match, on the invoice for a stray —
  with both org fingerprints, and never auto-matched by name (UC-BK-3);
- a credit note linked to no known invoice: ``credit_note_unlinked``
  (review, entity ``credit_note``).

Messages are finance-readable (amounts and currencies are not PII);
amount detail lives in evidence as well for the finance workbook.
``ready`` is true when no error- or review-severity finding remains.
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from typing import Any

from zohokit.core.context import RunContext
from zohokit.core.findings import Finding, Report, Severity
from zohokit.core.ids import canonical_json
from zohokit.core.money import MoneyError, quantize_money
from zohokit.core.money import parse as parse_amount
from zohokit.modules import Analysis
from zohokit.modules.books.entities import EntityEntry, org_fingerprint
from zohokit.modules.books.fx import FxRate, convert, lookup_rate
from zohokit.modules.books.period import in_window, record_date
from zohokit.modules.books.policy import MatchPolicy
from zohokit.modules.books.report import build_report

_CODE_SEVERITY: dict[str, Severity] = {
    "duplicate_or_missing_deal_id": Severity.ERROR,
    "entity_currency_mismatch": Severity.ERROR,
    "invalid_amount": Severity.ERROR,
    "missing_invoice": Severity.ERROR,
    "duplicate_invoice_reference": Severity.ERROR,
    "cross_entity_invoice": Severity.ERROR,
    "currency_mismatch": Severity.ERROR,
    "outside_tolerance": Severity.ERROR,
    "under_invoiced": Severity.ERROR,
    "over_invoiced": Severity.ERROR,
    "source_unavailable": Severity.ERROR,
    "credit_note_unlinked": Severity.REVIEW,
    "fx_rate_missing": Severity.REVIEW,
    "invalid_date": Severity.REVIEW,
    "within_tolerance": Severity.INFO,
    "draft_invoice_excluded": Severity.INFO,
    "void_invoice_excluded": Severity.INFO,
    "orphan_invoice_reference": Severity.ERROR,
}

_DRAFT_STATUSES = frozenset({"draft"})
_VOID_STATUSES = frozenset({"void", "voided", "cancelled", "canceled"})


def _parse_strict(value: Any) -> Decimal:
    """Strict string amount parsing (rejects floats, bools, bad grouping)."""
    if not isinstance(value, str):
        raise MoneyError(f"amount must be a decimal string, got {type(value).__name__}")
    return parse_amount(value)


def _custom_field_value(invoice: dict[str, Any], label: str) -> str:
    """Value of the custom field labelled *label* (list or mapping form)."""
    fields = invoice.get("custom_fields")
    if isinstance(fields, dict):
        value = fields.get(label, "")
        return str(value) if value is not None else ""
    if isinstance(fields, list):
        for entry in fields:
            if isinstance(entry, dict) and str(entry.get("label", "")) == label:
                value = entry.get("value", "")
                return str(value) if value is not None else ""
    return ""


def match_key(policy: MatchPolicy, deal: dict[str, Any], invoice: dict[str, Any]) -> bool:
    """Whether *invoice* keys to *deal* under the policy strategy."""
    strategy = policy.key_strategy
    if strategy == "crm_deal_id_in_invoice_custom_field":
        deal_id = str(deal.get("id", ""))
        if not deal_id:
            return False
        return _custom_field_value(invoice, policy.custom_field_label) == deal_id
    if strategy == "reference_number":
        ref = str(deal.get("reference_number", ""))
        if not ref:
            return False
        return str(invoice.get("reference_number", "")) == ref
    if strategy == "sales_order_link":
        for deal_field in ("salesorder_id", "salesorder_number"):
            deal_value = str(deal.get(deal_field, ""))
            if not deal_value:
                continue
            for inv_field in ("salesorder_id", "salesorder_number"):
                if str(invoice.get(inv_field, "")) == deal_value:
                    return True
        return False
    return False  # pragma: no cover - policy literal exhausts the cases


def _invoice_net(invoice: dict[str, Any]) -> Any:
    """Net amount raw value: ``net_amount``, else ``sub_total``, else ``total``."""
    for field in ("net_amount", "sub_total", "total"):
        if invoice.get(field) is not None:
            return invoice.get(field)
    return None


def _invoice_gross(invoice: dict[str, Any]) -> Any:
    """Gross amount raw value: ``total``, else ``net_amount``."""
    if invoice.get("total") is not None:
        return invoice.get("total")
    return invoice.get("net_amount")


def within_tolerance(diff: Decimal, deal_net: Decimal, policy: MatchPolicy) -> bool:
    """Whether ``|diff|`` fits every tolerance bound the policy states.

    Both bounds when both are given, the single stated bound when only
    one is given, and exact match (``diff == 0``) when neither is given.
    A policy that sets only ``pct`` never inherits a default ``abs``.
    """
    magnitude = abs(diff)
    checks: list[bool] = []
    if policy.tolerance.abs is not None:
        checks.append(magnitude <= policy.tolerance.abs)
    if policy.tolerance.pct is not None:
        pct_bound = abs(deal_net) * policy.tolerance.pct / Decimal(100)
        checks.append(magnitude <= pct_bound)
    if not checks:
        return diff == 0
    return all(checks)


def _fmt_amount(raw: Any) -> str:
    """Format a parsed amount as ``49,500.00`` (fallback: the raw text)."""
    try:
        return f"{Decimal(str(raw)):,.2f}"
    except Exception:
        return str(raw)


def _tolerance_text(policy: MatchPolicy) -> str:
    """Human-readable tolerance bounds, e.g. ``±1.00 and 0.5%``."""
    parts: list[str] = []
    if policy.tolerance.abs is not None:
        parts.append(f"\u00b1{_fmt_amount(policy.tolerance.abs)}")
    if policy.tolerance.pct is not None:
        parts.append(f"{policy.tolerance.pct}%")
    return " and ".join(parts) if parts else "exact match"


def _invoice_day(invoice: dict[str, Any]) -> date | None:
    """FX rate date for *invoice* (its own date, else ``None``)."""
    return record_date(invoice.get("date"))


class _Builder:
    """Collects v2 findings with stable, source-keyed identities."""

    def __init__(self, policy: MatchPolicy) -> None:
        self.findings: list[Finding] = []
        self.legacy: list[dict[str, str]] = []
        self.policy = policy

    def record(
        self,
        code: str,
        entity: str,
        entity_id: str,
        discriminator: str,
        evidence: dict[str, Any],
    ) -> None:
        message = _message(code, entity, entity_id, evidence, self.policy)
        self.legacy.append({"deal": entity_id, "code": code})
        self.findings.append(
            Finding.create(
                module="books",
                code=code,
                severity=_CODE_SEVERITY[code],
                entity=entity,
                entity_id=entity_id,
                message=message,
                evidence=evidence,
                discriminator=discriminator,
            )
        )


def _message(
    code: str,
    entity: str,
    entity_id: str,
    evidence: dict[str, Any],
    policy: MatchPolicy,
) -> str:
    """Finance-readable message for *code* (amounts/currency are not PII)."""
    tolerance = _tolerance_text(policy)
    if code == "outside_tolerance":
        net = _fmt_amount(evidence.get("deal_net", ""))
        total = _fmt_amount(evidence.get("invoiced_total", ""))
        diff = _fmt_amount(evidence.get("diff", ""))
        ccy = str(evidence.get("currency", ""))
        return (
            f"Invoiced {total} {ccy} against a deal net of {net} {ccy} "
            f"({diff}), outside tolerance ({tolerance})."
        )
    if code == "under_invoiced":
        net = _fmt_amount(evidence.get("deal_net", ""))
        total = _fmt_amount(evidence.get("invoiced_total", ""))
        diff = _fmt_amount(evidence.get("diff", ""))
        ccy = str(evidence.get("currency", ""))
        return (
            f"Deal {entity_id} under-invoiced: staged invoices total {total} {ccy} "
            f"against a deal net of {net} {ccy} ({diff}), outside tolerance "
            f"({tolerance})."
        )
    if code == "over_invoiced":
        net = _fmt_amount(evidence.get("deal_net", ""))
        total = _fmt_amount(evidence.get("invoiced_total", ""))
        diff = _fmt_amount(evidence.get("diff", ""))
        ccy = str(evidence.get("currency", ""))
        return (
            f"Deal {entity_id} over-invoiced: staged invoices total {total} {ccy} "
            f"against a deal net of {net} {ccy} (+{diff.lstrip('-')}), outside "
            f"tolerance ({tolerance})."
        )
    if code == "within_tolerance":
        net = _fmt_amount(evidence.get("deal_net", ""))
        total = _fmt_amount(evidence.get("invoiced_total", ""))
        ccy = str(evidence.get("currency", ""))
        return (
            f"Deal {entity_id} matched: invoiced {total} {ccy} against a deal "
            f"net of {net} {ccy}, within tolerance ({tolerance})."
        )
    if code == "missing_invoice":
        missing_net = evidence.get("deal_net")
        ccy = str(evidence.get("currency", ""))
        if missing_net not in (None, ""):
            return (
                f"Deal {entity_id} ({_fmt_amount(missing_net)} {ccy}) is missing its "
                f"invoice for the period."
            )
        return f"Deal {entity_id} is missing its invoice for the period."
    if code == "duplicate_invoice_reference":
        ids = evidence.get("invoice_ids") or []
        field = str(evidence.get("billing_plan_field", "Billing_Plan"))
        return (
            f"Deal {entity_id} has {len(ids)} invoices sharing its reference "
            f"({', '.join(str(item) for item in ids)}); staged billing needs "
            f"{field}."
        )
    if code == "cross_entity_invoice" and entity == "deal":
        inv = str(evidence.get("invoice_id", ""))
        deal_entity = str(evidence.get("deal_entity", ""))
        inv_entity = str(evidence.get("invoice_entity", ""))
        return f"Invoice {inv} for deal {entity_id} ({deal_entity}) was raised in {inv_entity}."
    if code == "cross_entity_invoice":
        inv_entity = str(evidence.get("invoice_entity", ""))
        deals = ", ".join(str(item) for item in evidence.get("candidate_deals", []))
        entities = ", ".join(str(item) for item in evidence.get("candidate_entities", []))
        return (
            f"Invoice {entity_id} ({inv_entity}) shares its customer with "
            f"deal(s) {deals} in {entities}; never matched by name."
        )
    if code == "orphan_invoice_reference":
        amount = evidence.get("invoice_amount")
        ccy = str(evidence.get("invoice_currency", ""))
        if amount not in (None, ""):
            return f"Invoice {entity_id} ({_fmt_amount(amount)} {ccy}) references no known deal."
        return f"Invoice {entity_id} references no known deal."
    if code == "credit_note_unlinked":
        amount = evidence.get("credit_note_amount")
        ccy = str(evidence.get("credit_note_currency", ""))
        linked = str(evidence.get("invoice_id", ""))
        if amount not in (None, ""):
            if linked:
                return (
                    f"Credit note {entity_id} ({_fmt_amount(amount)} {ccy}) links "
                    f"to unknown invoice {linked}."
                )
            return (
                f"Credit note {entity_id} ({_fmt_amount(amount)} {ccy}) links to no known invoice."
            )
        if linked:
            return f"Credit note {entity_id} links to unknown invoice {linked}."
        return f"Credit note {entity_id} links to no known invoice."
    if code == "fx_rate_missing":
        frm = str(evidence.get("from_currency", ""))
        to = str(evidence.get("to_currency", ""))
        day = str(evidence.get("invoice_date", ""))
        return (
            f"Deal {entity_id}: no exact {frm}->{to} rate for {day}; comparison "
            f"skipped, never guessed."
        )
    if code == "draft_invoice_excluded":
        inv = str(evidence.get("invoice_id", ""))
        return f"Invoice {inv} for deal {entity_id} is a draft, excluded by policy."
    if code == "void_invoice_excluded":
        inv = str(evidence.get("invoice_id", ""))
        status = str(evidence.get("status", "void"))
        return f"Invoice {inv} for deal {entity_id} is {status}, excluded by policy."
    if code == "invalid_amount":
        value = evidence.get("value")
        return (
            f"Row {entity_id} carries a malformed amount {value!r}; excluded "
            f"from amount comparison."
        )
    if code == "invalid_date":
        value = evidence.get("value")
        field = str(evidence.get("field", "date"))
        return (
            f"Row {entity_id} carries a missing or unparseable {field} "
            f"{value!r}; excluded from matching."
        )
    if code == "source_unavailable":
        return (
            f"Org pull for {entity_id} failed; its records are out of scope while others continue."
        )
    return f"{code} on {entity} {entity_id or '<missing>'}"


def analyze_recon(
    *,
    deals: list[dict[str, Any]],
    invoices: list[dict[str, Any]],
    credit_notes: list[dict[str, Any]] | None = None,
    policy: MatchPolicy,
    entities: dict[str, EntityEntry],
    org_ids: dict[str, str] | None = None,
    fx_rates: tuple[FxRate, ...] = (),
    unavailable: tuple[str, ...] = (),
) -> Analysis:
    """Reconcile one month across entities under *policy* (offline v2)."""
    builder = _Builder(policy)
    credit_notes = list(credit_notes or [])
    resolved_orgs = dict(org_ids or {})

    def _print(key: str) -> str | None:
        """Org fingerprint for *key*, or ``None`` when no profile org id.

        The key is omitted from evidence when no profile org id exists —
        never an empty string (UC-BK-3).
        """
        if key in resolved_orgs:
            return org_fingerprint(resolved_orgs[key])
        return None

    def _with_print(evidence: dict[str, Any], key: str, entity_key: str) -> dict[str, Any]:
        printed = _print(entity_key)
        if printed is not None:
            evidence[key] = printed
        return evidence

    for entity_key in sorted(set(unavailable)):
        if entity_key in entities:
            builder.record(
                "source_unavailable",
                "entity",
                entity_key,
                entity_key,
                _with_print({"entity_key": entity_key}, "org_fingerprint", entity_key),
            )
    dead = set(unavailable)

    # Row-level date validation (TK-FIX-2 style): a missing or
    # unparseable date never counts as in-window. The row gets
    # ``invalid_date`` (review) and is excluded from every matching
    # pass below, as ``invalid_amount`` rows are excluded from amount
    # comparison. Only applies to windowed runs (``policy.period`` set).
    bad_deals: set[str] = set()
    bad_invoices: set[str] = set()
    if policy.period is not None:
        for deal in deals:
            if not isinstance(deal, dict):
                continue
            deal_id = str(deal.get("id", ""))
            entity_key = str(deal.get("entity", ""))
            if entity_key in dead or entity_key not in entities:
                continue
            raw_date = deal.get("closing_date")
            if record_date(raw_date) is None:
                bad_deals.add(deal_id)
                builder.record(
                    "invalid_date",
                    "deal",
                    deal_id,
                    deal_id,
                    {
                        "row": "deal",
                        "field": "closing_date",
                        "value": raw_date,
                        "deal_entity": entity_key,
                    },
                )
        for inv in invoices:
            if not isinstance(inv, dict):
                continue
            invoice_id = str(inv.get("id", ""))
            entity_key = str(inv.get("entity", ""))
            if entity_key in dead or entity_key not in entities:
                continue
            raw_date = inv.get("date")
            if record_date(raw_date) is None:
                bad_invoices.add(invoice_id)
                builder.record(
                    "invalid_date",
                    "invoice",
                    invoice_id,
                    invoice_id,
                    {
                        "row": "invoice",
                        "field": "date",
                        "value": raw_date,
                        "invoice_entity": entity_key,
                    },
                )

    def deal_in_scope(deal: dict[str, Any]) -> bool:
        """Deals are windowed by closing date only in ``deal_closing_date`` mode."""
        period = policy.period
        if period is None or period.by != "deal_closing_date":
            return True
        return in_window(deal.get("closing_date"), start=period.start, end=period.end)

    def invoice_in_scope(inv: dict[str, Any]) -> bool:
        """Invoices are windowed by date only in ``invoice_date`` mode."""
        period = policy.period
        if period is None or period.by == "deal_closing_date":
            return True
        return in_window(inv.get("date"), start=period.start, end=period.end)

    for deal in deals:
        if not isinstance(deal, dict):
            continue
        deal_id = str(deal.get("id", ""))
        entity_key = str(deal.get("entity", ""))
        if entity_key in dead:
            continue
        if deal_id in bad_deals:
            continue
        entry = entities.get(entity_key)
        if entry is None:
            builder.record(
                "entity_currency_mismatch", "deal", deal_id, deal_id, {"entity_key": entity_key}
            )
            continue
        deal_ccy = str(deal.get("currency", ""))
        if deal_ccy != entry.currency:
            builder.record(
                "entity_currency_mismatch",
                "deal",
                deal_id,
                deal_id,
                _with_print(
                    {"entity_key": entity_key, "deal_entity": entity_key},
                    "org_fingerprint",
                    entity_key,
                ),
            )
        if not deal_in_scope(deal):
            continue
        try:
            deal_net: Decimal | None = _parse_strict(deal.get("net_amount"))
        except MoneyError:
            builder.record(
                "invalid_amount",
                "deal",
                deal_id,
                deal_id,
                {"row": "deal", "value": deal.get("net_amount"), "deal_entity": entity_key},
            )
            deal_net = None

        own = [
            inv
            for inv in invoices
            if isinstance(inv, dict)
            and str(inv.get("entity", "")) == entity_key
            and str(inv.get("id", "")) not in bad_invoices
            and invoice_in_scope(inv)
            and match_key(policy, deal, inv)
        ]
        effective: list[dict[str, Any]] = []
        for inv in own:
            status = str(inv.get("status", "sent")).casefold()
            invoice_id = str(inv.get("id", ""))
            if status in _DRAFT_STATUSES and not policy.include_draft:
                builder.record(
                    "draft_invoice_excluded",
                    "deal",
                    deal_id,
                    invoice_id or deal_id,
                    {
                        "invoice_id": invoice_id,
                        "status": str(inv.get("status", "sent")),
                        "deal_entity": entity_key,
                        "invoice_entity": entity_key,
                    },
                )
                continue
            if status in _VOID_STATUSES and not policy.include_void:
                builder.record(
                    "void_invoice_excluded",
                    "deal",
                    deal_id,
                    invoice_id or deal_id,
                    {
                        "invoice_id": invoice_id,
                        "status": str(inv.get("status", "sent")),
                        "deal_entity": entity_key,
                        "invoice_entity": entity_key,
                    },
                )
                continue
            effective.append(inv)

        for inv in invoices:
            if not isinstance(inv, dict) or str(inv.get("entity", "")) == entity_key:
                continue
            if str(inv.get("id", "")) in bad_invoices:
                continue
            if not invoice_in_scope(inv):
                continue
            other_key = str(inv.get("entity", ""))
            if other_key in dead or other_key not in entities:
                continue
            invoice_id = str(inv.get("id", ""))
            if not match_key(policy, deal, inv):
                continue
            # Key-matched across legal entities: misfiled, never auto-matched
            # (UC-BK-3). The deal keeps missing_invoice; the invoice is
            # flagged here naming both entities, with org fingerprints only
            # when a profile org id exists (omitted, never "").
            builder.record(
                "cross_entity_invoice",
                "deal",
                deal_id,
                invoice_id or deal_id,
                _with_print(
                    _with_print(
                        {
                            "invoice_id": invoice_id,
                            "deal_entity": entity_key,
                            "invoice_entity": other_key,
                        },
                        "entity_fingerprint",
                        entity_key,
                    ),
                    "invoice_org_fingerprint",
                    other_key,
                ),
            )

        if not effective:
            missing_evidence: dict[str, Any] = {"deal_entity": entity_key}
            if deal_net is not None:
                missing_evidence["deal_net"] = str(deal_net)
                missing_evidence["currency"] = deal_ccy
            builder.record("missing_invoice", "deal", deal_id, deal_id, missing_evidence)
            continue

        plan_field = (
            policy.allow_multiple_invoices_when.billing_plan_field
            if policy.allow_multiple_invoices_when
            else ""
        )
        staged = bool(plan_field and deal.get(plan_field))
        if len(effective) > 1 and not staged:
            builder.record(
                "duplicate_invoice_reference",
                "deal",
                deal_id,
                deal_id,
                {
                    "invoice_ids": sorted(str(inv.get("id", "")) for inv in effective),
                    "billing_plan_field": plan_field,
                    "deal_entity": entity_key,
                },
            )
            continue

        if deal_net is None:
            continue
        invoiced = Decimal("0")
        converted: list[dict[str, str]] = []
        skip_compare = False
        gross_rate = (
            policy.tax_table.get(str(deal.get("tax_name", "")))
            if policy.tax == "compare_gross_with_tax_table"
            else None
        )
        for inv in effective:
            invoice_id = str(inv.get("id", ""))
            inv_ccy = str(inv.get("currency", "")) or deal_ccy
            use_gross = gross_rate is not None
            raw_amount = _invoice_gross(inv) if use_gross else _invoice_net(inv)
            try:
                amount = _parse_strict(raw_amount)
            except MoneyError:
                builder.record(
                    "invalid_amount",
                    "deal",
                    deal_id,
                    invoice_id or deal_id,
                    {
                        "row": "invoice",
                        "value": raw_amount,
                        "invoice_id": invoice_id,
                        "deal_entity": entity_key,
                        "invoice_entity": entity_key,
                    },
                )
                skip_compare = True
                continue
            if inv_ccy != deal_ccy:
                day = _invoice_day(inv)
                rate_row = lookup_rate(fx_rates, on=day, frm=inv_ccy, to=deal_ccy) if day else None
                if rate_row is None:
                    builder.record(
                        "fx_rate_missing",
                        "deal",
                        deal_id,
                        invoice_id or deal_id,
                        {
                            "invoice_id": invoice_id,
                            "from_currency": inv_ccy,
                            "to_currency": deal_ccy,
                            "invoice_date": str(inv.get("date", "")),
                            "deal_net": str(deal_net),
                            "currency": deal_ccy,
                            "invoice_amount": str(raw_amount),
                            "invoice_currency": inv_ccy,
                            "deal_entity": entity_key,
                            "invoice_entity": entity_key,
                        },
                    )
                    skip_compare = True
                    continue
                amount = quantize_money(convert(amount, rate_row))
                converted.append(
                    {
                        "invoice_id": invoice_id,
                        "original": str(raw_amount),
                        "original_currency": inv_ccy,
                        "converted": str(amount),
                        "converted_currency": deal_ccy,
                        "rate": str(rate_row.rate),
                        "rate_source": rate_row.source,
                    }
                )
            invoiced += amount
        for cn in credit_notes:
            if not isinstance(cn, dict):
                continue
            linked_to = str(cn.get("invoice_id", ""))
            if linked_to and any(str(inv.get("id", "")) == linked_to for inv in effective):
                try:
                    cn_amount = _parse_strict(cn.get("net_amount", cn.get("total")))
                except MoneyError:
                    builder.record(
                        "invalid_amount",
                        "credit_note",
                        str(cn.get("id", "")),
                        str(cn.get("id", "")),
                        {
                            "row": "credit_note",
                            "value": cn.get("net_amount", cn.get("total")),
                            "credit_note_id": str(cn.get("id", "")),
                        },
                    )
                    skip_compare = True
                    continue
                invoiced -= cn_amount
        if skip_compare:
            continue
        target = deal_net
        tax_fallback = False
        if policy.tax == "compare_gross_with_tax_table":
            rate = policy.tax_table.get(str(deal.get("tax_name", "")))
            if rate is not None:
                target = deal_net * (Decimal(1) + rate / Decimal(100))
            else:
                # Unknown tax name: net-only comparison for this deal
                # (noted, never a guessed rate).
                tax_fallback = True
        diff = invoiced - target
        evidence: dict[str, Any] = {
            "deal_net": str(deal_net),
            "invoiced_total": str(invoiced),
            "currency": deal_ccy,
            "diff": str(diff),
            "deal_entity": entity_key,
        }
        if tax_fallback:
            evidence["tax_fallback_net"] = True
        if converted:
            evidence["conversions"] = converted
        if len(effective) == 1:
            if within_tolerance(diff, target, policy):
                builder.record("within_tolerance", "deal", deal_id, deal_id, evidence)
            else:
                builder.record("outside_tolerance", "deal", deal_id, deal_id, evidence)
        else:
            if within_tolerance(diff, target, policy):
                builder.record("within_tolerance", "deal", deal_id, deal_id, evidence)
            elif diff < 0:
                builder.record("under_invoiced", "deal", deal_id, deal_id, evidence)
            else:
                builder.record("over_invoiced", "deal", deal_id, deal_id, evidence)

    matched_ids = set()
    for deal in deals:
        if not isinstance(deal, dict):
            continue
        entity_key = str(deal.get("entity", ""))
        if entity_key in dead or entity_key not in entities:
            continue
        if str(deal.get("id", "")) in bad_deals:
            continue
        if not deal_in_scope(deal):
            continue
        for inv in invoices:
            if (
                isinstance(inv, dict)
                and str(inv.get("entity", "")) == entity_key
                and str(inv.get("id", "")) not in bad_invoices
                and invoice_in_scope(inv)
                and match_key(policy, deal, inv)
            ):
                matched_ids.add(str(inv.get("id", "")))
    for inv in invoices:
        if not isinstance(inv, dict):
            continue
        entity_key = str(inv.get("entity", ""))
        if entity_key in dead or entity_key not in entities:
            continue
        invoice_id = str(inv.get("id", ""))
        if invoice_id in matched_ids:
            continue
        if invoice_id in bad_invoices:
            continue
        if not invoice_in_scope(inv):
            continue
        key_matches_anywhere = any(
            isinstance(deal, dict)
            and str(deal.get("entity", "")) not in dead
            and str(deal.get("entity", "")) in entities
            and str(deal.get("id", "")) not in bad_deals
            and deal_in_scope(deal)
            and match_key(policy, deal, inv)
            for deal in deals
        )
        if key_matches_anywhere:
            # Misfiled (key-matched to a deal in another entity): flagged
            # via cross_entity_invoice on that deal, never an orphan.
            continue
        customer = str(inv.get("customer_name", ""))
        if customer:
            candidates: list[str] = []
            candidate_entities: list[str] = []
            candidate_prints: list[str] = []
            for deal in deals:
                if not isinstance(deal, dict):
                    continue
                other = str(deal.get("entity", ""))
                if other == entity_key or other in dead or other not in entities:
                    continue
                if str(deal.get("id", "")) in bad_deals:
                    continue
                if not deal_in_scope(deal):
                    continue
                if str(deal.get("customer_name", "")) == customer:
                    candidates.append(str(deal.get("id", "")))
                    candidate_entities.append(other)
                    printed = _print(other)
                    if printed is not None:
                        candidate_prints.append(printed)
            if candidates:
                # Stray invoice sharing a customer name across entities:
                # flagged once on the invoice (never matched by name),
                # naming the invoice entity and the candidate deal entities.
                distinct_entities = sorted(set(candidate_entities))
                stray_evidence: dict[str, Any] = {
                    "invoice_entity": entity_key,
                    "deal_entity": distinct_entities[0],
                    "candidate_deals": sorted(candidates),
                    "candidate_entities": distinct_entities,
                }
                if candidate_prints:
                    stray_evidence["candidate_fingerprints"] = sorted(set(candidate_prints))
                stray_evidence = _with_print(stray_evidence, "invoice_org_fingerprint", entity_key)
                builder.record(
                    "cross_entity_invoice",
                    "invoice",
                    invoice_id,
                    invoice_id,
                    stray_evidence,
                )
                continue
        status = str(inv.get("status", "sent")).casefold()
        if status in _DRAFT_STATUSES and not policy.include_draft:
            continue
        if status in _VOID_STATUSES and not policy.include_void:
            continue
        builder.record(
            "orphan_invoice_reference",
            "invoice",
            invoice_id,
            invoice_id,
            _with_print(
                {
                    "invoice_entity": entity_key,
                    "invoice_amount": str(_invoice_net(inv))
                    if _invoice_net(inv) is not None
                    else "",
                    "invoice_currency": str(inv.get("currency", "")),
                },
                "org_fingerprint",
                entity_key,
            ),
        )

    known_invoice_ids = {
        str(inv.get("id", ""))
        for inv in invoices
        if isinstance(inv, dict) and str(inv.get("entity", "")) not in dead
    }
    for cn in credit_notes:
        if not isinstance(cn, dict):
            continue
        cn_id = str(cn.get("id", ""))
        linked_to = str(cn.get("invoice_id", ""))
        if linked_to and linked_to in known_invoice_ids:
            continue
        cn_raw = cn.get("net_amount", cn.get("total"))
        builder.record(
            "credit_note_unlinked",
            "credit_note",
            cn_id,
            cn_id,
            {
                "credit_note_id": cn_id,
                "invoice_id": linked_to,
                "credit_note_amount": str(cn_raw) if cn_raw is not None else "",
                "credit_note_currency": str(cn.get("currency", "")),
                "credit_note_entity": str(cn.get("entity", "")),
            },
        )

    findings = sorted(builder.findings, key=lambda item: item.sort_key())
    ready = not any(item.severity in (Severity.ERROR, Severity.REVIEW) for item in findings)
    legacy = {
        "mode": "dry_run_only",
        "ready_for_sync": ready,
        "deal_count": len(deals),
        "invoice_count": len(invoices),
        "findings": sorted(builder.legacy, key=lambda item: (item["deal"], item["code"])),
        "created_invoices": 0,
    }
    return Analysis(findings=tuple(findings), legacy=legacy, ready=ready)


def run_recon(
    data: dict[str, Any],
    *,
    policy: MatchPolicy,
    entities: dict[str, EntityEntry],
    org_ids: dict[str, str] | None = None,
    fx_rates: tuple[FxRate, ...] = (),
    unavailable: tuple[str, ...] = (),
    ctx: RunContext,
) -> Report:
    """Run the v2 reconciliation and build the versioned report envelope."""
    deals = data.get("deals", [])
    invoices = data.get("invoices", [])
    credit_notes = data.get("credit_notes", [])
    if not isinstance(deals, list) or not isinstance(invoices, list):
        raise ValueError("deals and invoices must be lists")
    if not isinstance(credit_notes, list):
        raise ValueError("credit_notes must be a list")
    analysis = analyze_recon(
        deals=deals,
        invoices=invoices,
        credit_notes=credit_notes,
        policy=policy,
        entities=entities,
        org_ids=org_ids,
        fx_rates=fx_rates,
        unavailable=unavailable,
    )
    digest = hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()
    return build_report(analysis, ctx=ctx, inputs_sha256=digest)


__all__: list[str] = [
    "analyze_recon",
    "match_key",
    "run_recon",
    "within_tolerance",
]
