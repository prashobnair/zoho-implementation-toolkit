"""Read-only Zoho Books v3 readers (TK-CONN-6, UC-BK-1).

.. warning::
    These readers are **unverified**: the envelope shapes below are
    hand-written from the official Zoho Books API docs (see
    ``docs/API_CONTRACTS.md`` for the per-endpoint doc URL), and no
    request has ever been verified against a real Books org. Every call
    therefore requires ``experimental=True`` (``--experimental``) until
    a lead-confirmed live run verifies them.

Envelope shape (per https://www.zoho.com/books/api/v3/response/ and
https://www.zoho.com/books/api/v3/pagination/)::

    {"code": 0, "message": "success", "<resource>": [...],
     "page_context": {"page": 1, "per_page": 200, "has_more_page": false}}

``organization_id`` is a mandatory query parameter on every Books call
(except ``GET /organizations``, which lists the organizations); it is
asserted client-side before send, and every contract test asserts it is
present on the wire. A non-zero ``code`` maps to :class:`ConnectorError`
carrying the numeric code only — the Zoho ``message`` may carry record
values, so it is never echoed (value-free errors for public logs).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from zohokit.connectors.zoho.client import ZohoClient
from zohokit.connectors.zoho.errors import ConnectorError, ContractDriftError
from zohokit.connectors.zoho.models import ZohoResponse, validate_response

#: Books v3 API root path (the host varies per data centre:
#: ``https://www.zohoapis.<tld>/books/v3``).
BOOKS_BASE = "/books/v3"

#: Read-only scopes these readers need (requested, not granted yet).
BOOKS_READ_SCOPES = (
    "ZohoBooks.invoices.READ",
    "ZohoBooks.contacts.READ",
    "ZohoBooks.creditnotes.READ",
    "ZohoBooks.settings.READ",
)


def _require_org_id(organization_id: str | None, *, endpoint: str) -> str:
    """Return *organization_id* or fail before any request is built/sent."""
    if not organization_id:
        raise ConnectorError(
            f"{endpoint} requires an organization_id query parameter "
            "(Zoho Books v3): pass a non-empty organization id"
        )
    return organization_id


def _check_books_error(payload: Any, *, endpoint: str) -> None:
    """Map a non-zero Books ``code`` to ConnectorError (code only)."""
    if not isinstance(payload, dict):
        return
    code = payload.get("code")
    if code == 0 or code == "0":
        return
    if isinstance(code, bool):
        return
    if isinstance(code, int):
        raise ConnectorError(f"Zoho Books error {code} at {endpoint}")
    raise ConnectorError(f"Zoho Books request failed at {endpoint}")


def _response_json(response: httpx.Response, *, endpoint: str) -> Any:
    """Parse a 2xx body as JSON; a non-JSON body is a ConnectorError."""
    try:
        return response.json()
    except ValueError as exc:
        raise ConnectorError(f"{endpoint} returned non-JSON") from exc


class BooksPageContext(ZohoResponse):
    """Books ``page_context``: ``has_more_page`` drives pagination."""

    page: int = 1
    per_page: int = 200
    has_more_page: bool = False


class BooksListEnvelope(ZohoResponse):
    """One page of a Books list reply (resource key varies per endpoint)."""

    page_context: BooksPageContext | None = None


class BooksOrganization(ZohoResponse):
    """One entry of ``GET /books/v3/organizations`` (unverified shape)."""

    organization_id: str
    name: str = ""
    currency_code: str = ""


class BooksInvoice(ZohoResponse):
    """One Books invoice (list or detail; unverified shape)."""

    invoice_id: str
    invoice_number: str = ""
    reference_number: str = ""
    customer_id: str = ""
    customer_name: str = ""
    status: str = ""
    total: float | int | str = 0
    date: str = ""


class BooksContact(ZohoResponse):
    """One Books contact / customer (unverified shape)."""

    contact_id: str
    contact_name: str = ""
    customer_name: str = ""


class BooksCreditNote(ZohoResponse):
    """One Books credit note (unverified shape)."""

    creditnote_id: str
    creditnote_number: str = ""
    reference_number: str = ""
    customer_id: str = ""
    customer_name: str = ""
    status: str = ""
    total: float | int | str = 0
    date: str = ""


class BooksCurrency(ZohoResponse):
    """One Books currency (unverified shape)."""

    currency_id: str
    currency_code: str = ""
    currency_symbol: str = ""


class BooksTax(ZohoResponse):
    """One Books tax (unverified shape)."""

    tax_id: str
    tax_name: str = ""
    tax_percentage: float | int = 0


@dataclass(frozen=True)
class BooksPage:
    """One decoded Books list page: items plus whether more pages exist."""

    items: list[dict[str, Any]]
    has_more_page: bool


def _get_page(
    client: ZohoClient,
    path: str,
    resource: str,
    *,
    organization_id: str | None,
    page: int = 1,
    per_page: int = 200,
    extra_params: dict[str, Any] | None = None,
    experimental: bool = False,
) -> BooksPage:
    """GET one Books list page; ``organization_id`` always sent."""
    endpoint = path
    org_id = _require_org_id(organization_id, endpoint=endpoint)
    params: dict[str, Any] = {"organization_id": org_id, "page": page, "per_page": per_page}
    if extra_params:
        params.update(extra_params)
    response = client.get(path, params=params, endpoint=endpoint, experimental=experimental)
    if response.status_code >= 400:
        raise ConnectorError(
            f"Zoho Books request failed at {endpoint} with HTTP {response.status_code}"
        )
    payload = _response_json(response, endpoint=endpoint)
    _check_books_error(payload, endpoint=endpoint)
    if not isinstance(payload, dict) or resource not in payload:
        raise ContractDriftError(endpoint, f"{resource}: missing")
    items = payload[resource]
    if not isinstance(items, list):
        raise ContractDriftError(endpoint, f"{resource}: not a list")
    has_more = False
    context = payload.get("page_context")
    if isinstance(context, dict):
        has_more = bool(context.get("has_more_page", False))
    return BooksPage(items=items, has_more_page=has_more)


def iter_pages(
    client: ZohoClient,
    path: str,
    resource: str,
    *,
    organization_id: str | None,
    per_page: int = 200,
    experimental: bool = False,
) -> Any:
    """Yield every item across all pages (budget-capped by the client)."""
    page = 1
    while True:
        fetched = _get_page(
            client,
            path,
            resource,
            organization_id=organization_id,
            page=page,
            per_page=per_page,
            experimental=experimental,
        )
        yield from fetched.items
        if not fetched.has_more_page:
            return
        page += 1


def list_organizations(
    client: ZohoClient, *, experimental: bool = False
) -> list[BooksOrganization]:
    """GET ``/books/v3/organizations`` (no organization_id: it lists them)."""
    endpoint = f"{BOOKS_BASE}/organizations"
    response = client.get(endpoint, endpoint=endpoint, experimental=experimental)
    if response.status_code >= 400:
        raise ConnectorError(
            f"Zoho Books request failed at {endpoint} with HTTP {response.status_code}"
        )
    payload = _response_json(response, endpoint=endpoint)
    _check_books_error(payload, endpoint=endpoint)
    if not isinstance(payload, dict) or "organizations" not in payload:
        raise ContractDriftError(endpoint, "organizations: missing")
    raw = payload["organizations"]
    if not isinstance(raw, list):
        raise ContractDriftError(endpoint, "organizations: not a list")
    return [validate_response(BooksOrganization, endpoint=endpoint, payload=item) for item in raw]


def list_invoices(
    client: ZohoClient,
    *,
    organization_id: str | None,
    page: int = 1,
    per_page: int = 200,
    experimental: bool = False,
) -> BooksPage:
    """GET one page of ``/books/v3/invoices`` (unverified; needs ``--experimental``)."""
    return _get_page(
        client,
        f"{BOOKS_BASE}/invoices",
        "invoices",
        organization_id=organization_id,
        page=page,
        per_page=per_page,
        experimental=experimental,
    )


def get_invoice(
    client: ZohoClient,
    invoice_id: str,
    *,
    organization_id: str | None,
    experimental: bool = False,
) -> BooksInvoice:
    """GET ``/books/v3/invoices/{id}`` incl. ``reference_number`` + custom fields."""
    path = f"{BOOKS_BASE}/invoices/{invoice_id}"
    org_id = _require_org_id(organization_id, endpoint=path)
    # Static endpoint label: the id must never reach logs or error text.
    endpoint = f"{BOOKS_BASE}/invoices/{{id}}"
    response = client.get(
        path, params={"organization_id": org_id}, endpoint=endpoint, experimental=experimental
    )
    if response.status_code >= 400:
        raise ConnectorError(
            f"Zoho Books request failed at {endpoint} with HTTP {response.status_code}"
        )
    payload = _response_json(response, endpoint=endpoint)
    _check_books_error(payload, endpoint=endpoint)
    if not isinstance(payload, dict) or "invoice" not in payload:
        raise ContractDriftError(endpoint, "invoice: missing")
    return validate_response(BooksInvoice, endpoint=endpoint, payload=payload["invoice"])


def list_contacts(
    client: ZohoClient,
    *,
    organization_id: str | None,
    page: int = 1,
    per_page: int = 200,
    experimental: bool = False,
) -> BooksPage:
    """GET one page of ``/books/v3/contacts`` (unverified; needs ``--experimental``)."""
    return _get_page(
        client,
        f"{BOOKS_BASE}/contacts",
        "contacts",
        organization_id=organization_id,
        page=page,
        per_page=per_page,
        experimental=experimental,
    )


def list_creditnotes(
    client: ZohoClient,
    *,
    organization_id: str | None,
    page: int = 1,
    per_page: int = 200,
    experimental: bool = False,
) -> BooksPage:
    """GET one page of ``/books/v3/creditnotes`` (unverified; needs ``--experimental``)."""
    return _get_page(
        client,
        f"{BOOKS_BASE}/creditnotes",
        "creditnotes",
        organization_id=organization_id,
        page=page,
        per_page=per_page,
        experimental=experimental,
    )


def list_currencies(
    client: ZohoClient,
    *,
    organization_id: str | None,
    page: int = 1,
    per_page: int = 200,
    experimental: bool = False,
) -> BooksPage:
    """GET one page of ``/books/v3/settings/currencies`` (unverified)."""
    return _get_page(
        client,
        f"{BOOKS_BASE}/settings/currencies",
        "currencies",
        organization_id=organization_id,
        page=page,
        per_page=per_page,
        experimental=experimental,
    )


def list_taxes(
    client: ZohoClient,
    *,
    organization_id: str | None,
    page: int = 1,
    per_page: int = 200,
    experimental: bool = False,
) -> BooksPage:
    """GET one page of ``/books/v3/settings/taxes`` (unverified)."""
    return _get_page(
        client,
        f"{BOOKS_BASE}/settings/taxes",
        "taxes",
        organization_id=organization_id,
        page=page,
        per_page=per_page,
        experimental=experimental,
    )


__all__: list[str] = [
    "BOOKS_BASE",
    "BOOKS_READ_SCOPES",
    "BooksContact",
    "BooksCreditNote",
    "BooksCurrency",
    "BooksInvoice",
    "BooksOrganization",
    "BooksPage",
    "BooksPageContext",
    "BooksTax",
    "get_invoice",
    "iter_pages",
    "list_contacts",
    "list_creditnotes",
    "list_currencies",
    "list_invoices",
    "list_organizations",
    "list_taxes",
]
