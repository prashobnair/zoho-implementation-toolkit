"""Books v3 reader replay over synthetic envelopes (TK-CONN-6).

The Books v3 endpoints are `unverified` (see ``docs/API_CONTRACTS.md``):
live calls need ``--experimental``. These tests replay synthetic
cassettes shaped like the official Books envelopes
(``{"code": 0, "message": "success", "<resource>": [...],
"page_context": {"page": N, "per_page": N, "has_more_page": bool}}``,
confirmed against the official docs via webfetch) through the shared
GET-only client — no network, no Zoho calls. Every test asserts
``organization_id`` rides on every request.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from zohokit.connectors.zoho.books import (
    BOOKS_READ_SCOPES,
    get_invoice,
    iter_pages,
    list_contacts,
    list_creditnotes,
    list_currencies,
    list_invoices,
    list_organizations,
    list_taxes,
)
from zohokit.connectors.zoho.client import ZohoClient
from zohokit.connectors.zoho.errors import ConnectorError

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parent.parent.parent
CASSETTES = ROOT / "tests" / "contract" / "cassettes"

ORG_ID = "555000001"

SEEN: list[httpx.QueryParams] = []


def _body(name: str) -> dict[str, object]:
    envelope = json.loads((CASSETTES / name).read_text(encoding="utf-8"))
    body = envelope["response"]["body"]
    assert isinstance(body, dict)
    return body


def _client() -> ZohoClient:
    bodies = {
        "/books/v3/organizations": _body("books_organizations.json"),
        "/books/v3/invoices": None,  # paged below by ?page=
        "/books/v3/invoices/555000201": _body("books_invoice_detail.json"),
        "/books/v3/contacts": _body("books_contacts.json"),
        "/books/v3/creditnotes": _body("books_creditnotes.json"),
        "/books/v3/settings/currencies": _body("books_currencies.json"),
        "/books/v3/settings/taxes": _body("books_taxes.json"),
    }
    pages = {
        "1": _body("books_invoices_p1.json"),
        "2": _body("books_invoices_p2.json"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        SEEN.append(request.url.params)
        if request.url.path == "/books/v3/invoices":
            page = request.url.params.get("page", "1")
            body = pages.get(page)
            if body is None:
                return httpx.Response(404, json={"code": 1001, "message": "no such page"})
            return httpx.Response(200, json=body)
        body = bodies.get(request.url.path)
        if body is None:
            return httpx.Response(404, json={"code": 1001, "message": "not found"})
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    return ZohoClient("https://www.zohoapis.in", transport=transport)


def _clear_seen() -> None:
    SEEN.clear()


def test_books_cassettes_use_code_envelope_with_page_context() -> None:
    for name in (
        "books_invoices_p1.json",
        "books_invoices_p2.json",
        "books_contacts.json",
        "books_creditnotes.json",
        "books_currencies.json",
        "books_taxes.json",
    ):
        body = _body(name)
        assert body["code"] == 0
        assert body["message"] == "success"
        assert isinstance(body["page_context"], dict)
    assert _body("books_invoices_p1.json")["page_context"]["has_more_page"] is True
    assert _body("books_invoices_p2.json")["page_context"]["has_more_page"] is False
    detail = _body("books_invoice_detail.json")
    assert detail["code"] == 0
    assert detail["invoice"]["reference_number"] == "REF-001"
    assert detail["invoice"]["custom_fields"] == [{"label": "CRM Deal ID", "value": "d-in-01"}]


def test_books_readers_need_experimental() -> None:
    client = _client()
    with pytest.raises(ConnectorError, match="unverified"):
        list_invoices(client, organization_id=ORG_ID)
    with pytest.raises(ConnectorError, match="unverified"):
        list_organizations(client)


def test_organization_id_asserted_on_every_request() -> None:
    client = _client()
    _clear_seen()
    list_organizations(client, experimental=True)
    list_invoices(client, organization_id=ORG_ID, experimental=True)
    get_invoice(client, "555000201", organization_id=ORG_ID, experimental=True)
    list_contacts(client, organization_id=ORG_ID, experimental=True)
    list_creditnotes(client, organization_id=ORG_ID, experimental=True)
    list_currencies(client, organization_id=ORG_ID, experimental=True)
    list_taxes(client, organization_id=ORG_ID, experimental=True)
    assert len(SEEN) == 7
    for params in SEEN[1:]:
        assert params.get("organization_id") == ORG_ID


def test_missing_organization_id_fails_before_send() -> None:
    client = _client()
    _clear_seen()
    with pytest.raises(ConnectorError, match="organization_id"):
        list_invoices(client, organization_id=None, experimental=True)
    with pytest.raises(ConnectorError, match="organization_id"):
        get_invoice(client, "555000201", organization_id="", experimental=True)
    assert SEEN == []


def test_invoice_pagination_follows_has_more_page() -> None:
    client = _client()
    _clear_seen()
    items = list(
        iter_pages(
            client, "/books/v3/invoices", "invoices", organization_id=ORG_ID, experimental=True
        )
    )
    assert [item["invoice_id"] for item in items] == ["555000201", "555000202", "555000203"]
    assert [params.get("page") for params in SEEN] == ["1", "2"]
    assert all(params.get("organization_id") == ORG_ID for params in SEEN)


def test_invoice_detail_carries_reference_and_custom_fields() -> None:
    client = _client()
    invoice = get_invoice(client, "555000201", organization_id=ORG_ID, experimental=True)
    assert invoice.reference_number == "REF-001"
    assert invoice.status == "sent"
    assert invoice.raw_extra["custom_fields"] == [{"label": "CRM Deal ID", "value": "d-in-01"}]


def test_books_error_code_maps_without_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"code": 57, "message": "secret customer value must not leak"}
        )

    client = ZohoClient("https://www.zohoapis.in", transport=httpx.MockTransport(handler))
    with pytest.raises(ConnectorError) as excinfo:
        list_invoices(client, organization_id=ORG_ID, experimental=True)
    assert "57" in str(excinfo.value)
    assert "secret customer value" not in str(excinfo.value)


def test_books_read_scopes_are_read_only() -> None:
    from zohokit.connectors.zoho.scopes import READ_SCOPES, find_over_privileged

    assert sorted(BOOKS_READ_SCOPES) == [
        "ZohoBooks.contacts.READ",
        "ZohoBooks.creditnotes.READ",
        "ZohoBooks.invoices.READ",
        "ZohoBooks.settings.READ",
    ]
    assert sorted(READ_SCOPES["books"]) == sorted(BOOKS_READ_SCOPES)
    assert find_over_privileged(list(BOOKS_READ_SCOPES)) == []
