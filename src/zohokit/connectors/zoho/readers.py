"""Shared read helpers for Zoho CRM v8 (one parser per endpoint).

Doctor and smoke previously parsed ``/crm/v8/org`` through two independent
inline copies. The copies agreed on synthetic payloads but diverged live:
doctor built its API client without ever calling ``ensure_fresh()``, so its
org read went out with no ``Authorization`` header. Zoho answered ``401``
with an error body (``{"code": ..., "status": "error", ...}``, no ``org``
key), which the inline ``OrgResponse`` validation reported as
``contract_drift ... org: missing`` — while the authenticated smoke read of
the same endpoint passed. The record reads had the symmetric flaw: they sent
no ``fields`` query parameter (mandatory in v8 per
https://www.zoho.com/crm/developer/docs/api/v8/get-records.html), so Zoho
answered ``400 REQUIRED_PARAM_MISSING`` error bodies that surfaced as
``contract_drift ... data: missing``.

Both paths now funnel through this module:

- :func:`authenticated_client` builds the GET-only client from a fresh
  access token, so doctor and smoke authenticate identically.
- :func:`read_org` is the single org parser used by doctor and smoke.
- :func:`read_records` always sends the mandatory ``fields`` parameter
  (rejected client-side before send when empty), maps HTTP 204 to a valid
  empty page, and maps Zoho error bodies to :class:`ConnectorError`
  carrying the Zoho code only — never values.

All messages here are value-free (endpoint + field location / error type /
Zoho code only) so they are safe for public logs and evidence bundles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

from zohokit.connectors.zoho.auth import TokenManager
from zohokit.connectors.zoho.budget import CallBudget
from zohokit.connectors.zoho.client import ZohoClient
from zohokit.connectors.zoho.errors import ConnectorError, ContractDriftError
from zohokit.connectors.zoho.models import (
    OrgInfo,
    RecordPage,
    RecordPageInfo,
    ZohoResponse,
    unwrap_org,
    validate_response,
)

#: Minimal read-only field list sent per module. ``fields`` is mandatory in
#: CRM v8 when listing records (see the get-records doc URL in
#: ``docs/API_CONTRACTS.md``): ``id`` + ``Created_Time`` plus the module's
#: name field.
RECORD_FIELDS: dict[str, tuple[str, ...]] = {
    "Leads": ("id", "Created_Time", "Last_Name"),
    "Contacts": ("id", "Created_Time", "Last_Name"),
    "Deals": ("id", "Created_Time", "Deal_Name"),
}

#: Page size for the smoke record reads (minimal, read-only).
RECORD_SMOKE_PER_PAGE = 5

#: Zoho error codes are upper-snake constants (e.g. REQUIRED_PARAM_MISSING).
#: Only a payload ``code`` matching this shape is echoed; anything else
#: falls back to a generic HTTP message so values can never leak.
_ERROR_CODE_RE = re.compile(r"[A-Z0-9_]{1,64}")


def authenticated_client(
    api_base: str,
    manager: TokenManager,
    budget: CallBudget,
    transport: httpx.BaseTransport,
) -> ZohoClient:
    """Build the GET-only API client with a fresh access token.

    Every live reader (doctor, smoke) builds its client here, so none of
    them can silently send unauthenticated reads again.
    """
    access_token = manager.ensure_fresh()
    return ZohoClient(
        api_base,
        transport=transport,
        token_provider=lambda: access_token,
        budget=budget,
    )


def raise_for_zoho_error(response: httpx.Response, *, endpoint: str) -> None:
    """Map a 4xx/5xx Zoho reply to ConnectorError carrying the Zoho code only.

    Zoho error bodies look like ``{"code": "...", "status": "error", ...}``;
    only the ``code`` constant is echoed (``message``/``details`` may carry
    record values, so they are never included). A non-JSON or codeless error
    falls back to a generic HTTP message. Non-error statuses are a no-op.
    """
    if response.status_code < 400:
        return
    code = ""
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        candidate = payload.get("code")
        if isinstance(candidate, str) and _ERROR_CODE_RE.fullmatch(candidate):
            code = candidate
    if code:
        raise ConnectorError(f"Zoho error {code} at {endpoint}")
    raise ConnectorError(f"Zoho request failed at {endpoint} with HTTP {response.status_code}")


def _response_json(response: httpx.Response, *, endpoint: str) -> Any:
    """Parse a 2xx body as JSON; a non-JSON body is a ConnectorError."""
    try:
        return response.json()
    except ValueError as exc:
        raise ConnectorError(f"{endpoint} returned non-JSON") from exc


@dataclass(frozen=True)
class OrgRead:
    """One org read: the validated org plus the raw date header (if any)."""

    org: OrgInfo
    date_header: str | None


def read_org(client: ZohoClient, *, experimental: bool = False) -> OrgRead:
    """GET ``/crm/v8/org`` and return the single shared org parse.

    Used by both doctor and smoke so the two can never disagree again.
    """
    endpoint = "/crm/v8/org"
    response = client.get(endpoint, endpoint=endpoint, experimental=experimental)
    raise_for_zoho_error(response, endpoint=endpoint)
    if response.status_code == 204:
        raise ContractDriftError(endpoint, "org: empty response (HTTP 204)")
    payload = _response_json(response, endpoint=endpoint)
    return OrgRead(
        org=unwrap_org(payload, endpoint=endpoint),
        date_header=response.headers.get("date"),
    )


def read_records(
    client: ZohoClient,
    module: str,
    *,
    fields: tuple[str, ...] | list[str] | None = None,
    page: int = 1,
    per_page: int = RECORD_SMOKE_PER_PAGE,
    experimental: bool = False,
) -> RecordPage:
    """GET one page of ``/crm/v8/{module}`` records (read-only).

    ``fields`` is mandatory in CRM v8; it defaults to
    :data:`RECORD_FIELDS` for the module. An empty field list is rejected
    client-side — before any request is built or sent — so we never rely on
    the server's ``REQUIRED_PARAM_MISSING`` error. HTTP 204 (a module with
    no records) is a valid empty page, not drift.
    """
    endpoint = f"/crm/v8/{module}"
    resolved = tuple(fields) if fields is not None else RECORD_FIELDS.get(module, ())
    if not resolved:
        raise ConnectorError(
            f"{endpoint} requires a 'fields' query parameter (CRM v8): pass a non-empty field list"
        )
    params: dict[str, Any] = {
        "fields": ",".join(resolved),
        "page": page,
        "per_page": per_page,
    }
    response = client.get(endpoint, params=params, endpoint=endpoint, experimental=experimental)
    raise_for_zoho_error(response, endpoint=endpoint)
    if response.status_code == 204:
        return RecordPage(data=[], info=RecordPageInfo(more_records=False))
    payload = _response_json(response, endpoint=endpoint)
    return validate_response(RecordPage, endpoint=endpoint, payload=payload)


def read_model(
    client: ZohoClient,
    path: str,
    model: type[ZohoResponse],
    *,
    params: dict[str, Any] | None = None,
    experimental: bool = False,
) -> ZohoResponse:
    """GET *path* and validate it as *model* (Zoho errors map, never drift)."""
    endpoint = path.split("?")[0]
    response = client.get(path, params=params, endpoint=endpoint, experimental=experimental)
    raise_for_zoho_error(response, endpoint=endpoint)
    if response.status_code == 204:
        raise ContractDriftError(endpoint, "empty response (HTTP 204)")
    payload = _response_json(response, endpoint=endpoint)
    return validate_response(model, endpoint=endpoint, payload=payload)


__all__: list[str] = [
    "RECORD_FIELDS",
    "RECORD_SMOKE_PER_PAGE",
    "OrgRead",
    "authenticated_client",
    "raise_for_zoho_error",
    "read_model",
    "read_org",
    "read_records",
]
