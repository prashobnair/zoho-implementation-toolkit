"""Read-only Zoho pulls for month-end recon (TK-CONN-6, UC-BK-1).

Books v3 endpoints here are **unverified** against a real Books org
(envelope shapes follow the official Books v3 docs; see
``docs/API_CONTRACTS.md``), so the Books pull exists only behind
``--experimental`` and warns per STD-C2. CRM Deals reads go through the
existing live-verified GET-only CRM v8 reader
(:func:`read_records`, which always sends the mandatory ``fields=``
list). Tests replay synthetic cassettes shaped like those envelopes
through a mock transport; no call here can write (GET-only client,
budget-capped).

``live_pull`` returns one org bundle per entity key with the raw list
payloads plus mapped recon shapes for invoices/credit notes.
``live_pull_deals`` reads CRM Deals live under the policy
``crm_fields`` mapping and assigns each deal to its entity via the
entity map's ``crm_criteria``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from zohokit.connectors.zoho.auth import TokenManager
from zohokit.connectors.zoho.books import (
    BOOKS_BASE,
    iter_pages,
    list_currencies,
    list_taxes,
)
from zohokit.connectors.zoho.budget import DEFAULT_MAX_API_CALLS, CallBudget
from zohokit.connectors.zoho.client import ZohoClient
from zohokit.connectors.zoho.dc import DC_TABLE
from zohokit.connectors.zoho.errors import ConnectorError, ContractDriftError
from zohokit.connectors.zoho.profiles import load_profile
from zohokit.connectors.zoho.readers import authenticated_client, read_records
from zohokit.modules.books.entities import deal_in_entity
from zohokit.modules.books.period import in_window

#: Inner transport factory for API reads (tests inject a mock).
TRANSPORT_FACTORY: Callable[[], httpx.BaseTransport] = httpx.HTTPTransport

#: CRM Deals page size for the live recon read (read-only, budget-capped).
CRM_DEALS_PER_PAGE = 200


def map_invoice(entity_key: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Map one Books invoice payload to the offline recon invoice shape."""
    custom_fields = raw.get("custom_fields")
    if isinstance(custom_fields, dict):
        custom_list = [
            {"label": str(label), "value": "" if value is None else str(value)}
            for label, value in custom_fields.items()
        ]
    elif isinstance(custom_fields, list):
        custom_list = [
            {
                "label": str(entry.get("label", "")),
                "value": "" if entry.get("value") is None else str(entry.get("value")),
            }
            for entry in custom_fields
            if isinstance(entry, dict)
        ]
    else:
        custom_list = []
    return {
        "id": str(raw.get("invoice_id", "")),
        "entity": entity_key,
        "currency": str(raw.get("currency_code", "")),
        "net_amount": str(raw.get("sub_total", raw.get("total", "0"))),
        "total": str(raw.get("total", "0")),
        "sub_total": str(raw.get("sub_total", raw.get("total", "0"))),
        "reference_number": str(raw.get("reference_number", "")),
        "salesorder_id": str(raw.get("salesorder_id", "")),
        "salesorder_number": str(raw.get("salesorder_number", "")),
        "customer_id": str(raw.get("customer_id", "")),
        "customer_name": str(raw.get("customer_name", "")),
        "status": str(raw.get("status", "sent")),
        "date": str(raw.get("date", "")),
        "custom_fields": custom_list,
    }


def map_credit_note(entity_key: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Map one Books credit-note payload to the offline recon shape."""
    invoices = raw.get("invoices_credited") or raw.get("invoices") or []
    linked = ""
    if isinstance(invoices, list):
        for entry in invoices:
            if isinstance(entry, dict) and entry.get("invoice_id"):
                linked = str(entry.get("invoice_id"))
                break
    return {
        "id": str(raw.get("creditnote_id", "")),
        "entity": entity_key,
        "currency": str(raw.get("currency_code", "")),
        "net_amount": str(raw.get("total", "0")),
        "total": str(raw.get("total", "0")),
        "reference_number": str(raw.get("reference_number", "")),
        "customer_id": str(raw.get("customer_id", "")),
        "customer_name": str(raw.get("customer_name", "")),
        "status": str(raw.get("status", "open")),
        "date": str(raw.get("date", "")),
        "invoice_id": linked or str(raw.get("invoice_id", "")),
    }


def crm_deal_fields(crm_fields: Any) -> tuple[str, ...]:
    """Explicit CRM ``fields=`` list for the Deals read (v8 requires it).

    ``id`` plus every mapped field, de-duplicated in order. The reader
    rejects an empty list before send, so this never relies on the
    server's ``REQUIRED_PARAM_MISSING`` error.
    """
    wanted = (
        "id",
        str(crm_fields.amount),
        str(crm_fields.closing_date),
        str(crm_fields.currency),
        str(crm_fields.customer),
        str(crm_fields.billing_plan),
        str(crm_fields.entity),
    )
    seen: list[str] = []
    for name in wanted:
        if name and name not in seen:
            seen.append(name)
    return tuple(seen)


def map_deal(
    entity_key: str, raw: dict[str, Any], crm_fields: Any, billing_plan_field: str = ""
) -> dict[str, Any]:
    """Map one CRM Deal payload to the offline recon deal shape."""

    def _text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return ""
        return str(value)

    plan_field = billing_plan_field or "Billing_Plan"
    mapped: dict[str, Any] = {
        "id": _text(raw.get("id", "")),
        "entity": entity_key,
        "currency": _text(raw.get(str(crm_fields.currency), "")),
        "net_amount": _text(raw.get(str(crm_fields.amount), "0")),
        "customer_name": _text(raw.get(str(crm_fields.customer), "")),
        "closing_date": _text(raw.get(str(crm_fields.closing_date), "")),
        plan_field: _text(raw.get(str(crm_fields.billing_plan), "")),
        "reference_number": _text(raw.get("reference_number", "")),
        "salesorder_id": _text(raw.get("salesorder_id", "")),
        "salesorder_number": _text(raw.get("salesorder_number", "")),
    }
    return mapped


def live_pull_deals(
    profile: str,
    entities: dict[str, Any],
    crm_fields: Any,
    *,
    period_by: str | None = None,
    period_start: Any = None,
    period_end: Any = None,
    billing_plan_field: str = "",
    max_api_calls: int | None = None,
    transport_factory: Callable[[], httpx.BaseTransport] | None = None,
) -> list[dict[str, Any]]:
    """Read CRM Deals live and map them to offline recon deals (UC-BK-1).

    Deals come through the existing GET-only CRM v8 reader with the
    explicit ``fields=`` list from :func:`crm_deal_fields` (v8 requires
    it), paged until ``more_records`` is false. The run is budget-capped
    (the client fails closed on exhaustion). Each deal is assigned to
    the first (sorted) entity whose ``crm_criteria`` matches the raw CRM
    record; deals matching no entity keep ``entity ""`` so the engine
    isolates them via ``entity_currency_mismatch``. The period window
    applies client-side to dated deals (missing/unparseable dates pass
    through so the engine flags ``invalid_date``); dated deals outside
    the window are dropped here.
    """
    from zohokit.modules.books.policy import CrmDealFields as _CrmDealFields

    fields_model = crm_fields if isinstance(crm_fields, _CrmDealFields) else _CrmDealFields()
    fields = crm_deal_fields(fields_model)
    current = load_profile(profile)
    budget = CallBudget(max_calls=max_api_calls or DEFAULT_MAX_API_CALLS)
    factory = transport_factory or TRANSPORT_FACTORY
    manager = TokenManager(dc=current.dc, profile=current.name, transport_factory=factory)
    api_base = DC_TABLE[current.dc].api_base
    client: ZohoClient = authenticated_client(api_base, manager, budget, factory())
    ordered_keys = sorted(entities)
    deals: list[dict[str, Any]] = []
    page = 1
    while True:
        fetched = read_records(
            client,
            "Deals",
            fields=list(fields),
            page=page,
            per_page=CRM_DEALS_PER_PAGE,
            experimental=True,
        )
        for item in fetched.data:
            if not isinstance(item, dict):
                continue
            entity_key = ""
            for key in ordered_keys:
                if deal_in_entity(item, entities[key]):
                    entity_key = key
                    break
            mapped = map_deal(entity_key, item, fields_model, billing_plan_field)
            if period_by == "deal_closing_date" and period_start is not None:
                if not in_window(mapped.get("closing_date"), start=period_start, end=period_end):
                    continue
            deals.append(mapped)
        if not fetched.more_records:
            return deals
        page += 1


def live_pull(
    profile: str,
    entity_orgs: dict[str, str],
    *,
    max_api_calls: int | None = None,
    transport_factory: Callable[[], httpx.BaseTransport] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Pull invoices, credit notes, contacts, currencies and taxes per org.

    *entity_orgs* maps entity key → Books organization id (resolved from
    the local profile by the caller). Returns ``{entity_key: {"invoices",
    "credit_notes", "contacts", "currencies", "taxes"}}`` with mapped
    recon shapes for invoices/credit notes and raw list payloads for the
    rest. GET-only, budget-capped, experimental-gated by the readers.

    Returns ``(bundles, unavailable)``: one org bundle per reachable
    entity key, plus the entity keys whose pull failed (malformed org
    response → the caller reports ``source_unavailable`` for that org
    while the others continue, TK-BK-F8). Failure reasons are never
    returned (value-free errors for public logs).
    """
    current = load_profile(profile)
    budget = CallBudget(max_calls=max_api_calls or DEFAULT_MAX_API_CALLS)
    factory = transport_factory or TRANSPORT_FACTORY
    manager = TokenManager(dc=current.dc, profile=current.name, transport_factory=factory)
    # Reader paths are absolute from the API root (``/books/v3/...``),
    # like the CRM readers — so the client sits on the DC api base.
    api_base = DC_TABLE[current.dc].api_base
    client: ZohoClient = authenticated_client(api_base, manager, budget, factory())
    bundles: dict[str, dict[str, Any]] = {}
    unavailable: list[str] = []
    for entity_key, org_id in entity_orgs.items():
        try:
            bundles[entity_key] = _pull_org(client, entity_key, org_id)
        except (ConnectorError, ContractDriftError):
            unavailable.append(entity_key)
    return bundles, unavailable


def _pull_org(client: ZohoClient, entity_key: str, org_id: str) -> dict[str, Any]:
    """Pull one org's lists (any failure marks the org unavailable)."""
    invoices = [
        map_invoice(entity_key, dict(item))
        for item in iter_pages(
            client,
            f"{BOOKS_BASE}/invoices",
            "invoices",
            organization_id=org_id,
            experimental=True,
        )
        if isinstance(item, dict)
    ]
    credit_notes = [
        map_credit_note(entity_key, dict(item))
        for item in iter_pages(
            client,
            f"{BOOKS_BASE}/creditnotes",
            "creditnotes",
            organization_id=org_id,
            experimental=True,
        )
        if isinstance(item, dict)
    ]
    contacts = [
        dict(item)
        for item in iter_pages(
            client,
            f"{BOOKS_BASE}/contacts",
            "contacts",
            organization_id=org_id,
            experimental=True,
        )
        if isinstance(item, dict)
    ]
    currencies = list_currencies(client, organization_id=org_id, experimental=True).items
    taxes = list_taxes(client, organization_id=org_id, experimental=True).items
    return {
        "invoices": invoices,
        "credit_notes": credit_notes,
        "contacts": contacts,
        "currencies": [dict(item) for item in currencies if isinstance(item, dict)],
        "taxes": [dict(item) for item in taxes if isinstance(item, dict)],
    }


__all__: list[str] = [
    "CRM_DEALS_PER_PAGE",
    "TRANSPORT_FACTORY",
    "crm_deal_fields",
    "live_pull",
    "live_pull_deals",
    "map_credit_note",
    "map_deal",
    "map_invoice",
]
