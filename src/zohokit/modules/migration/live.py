"""Live target reads for migration preflight (TK-MIG-F3, TK-MIG-F7).

Field metadata comes from the verified ``/crm/v8/settings/fields``
endpoint (no ``--experimental`` needed); owner emails resolve through
the verified ``/crm/v8/users`` endpoint (PR B). Only verified endpoints
are called. Profile handling mirrors the release live path: named
profile, no default, budget cap, injectable transport for tests.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from zohokit.connectors.zoho.auth import TokenManager
from zohokit.connectors.zoho.budget import DEFAULT_MAX_API_CALLS, CallBudget
from zohokit.connectors.zoho.client import ZohoClient
from zohokit.connectors.zoho.dc import DC_TABLE
from zohokit.connectors.zoho.models import FieldsResponse, RecordPage, unwrap_fields
from zohokit.connectors.zoho.profiles import load_profile
from zohokit.connectors.zoho.readers import authenticated_client, read_model
from zohokit.modules.migration.metadata import FieldMeta, TargetMetadata
from zohokit.modules.migration.owners import users_from_envelope
from zohokit.modules.migration.target_dedupe import SearchFn, target_fingerprint

#: Inner transport factory for API reads (tests inject a mock).
TRANSPORT_FACTORY: Callable[[], httpx.BaseTransport] = httpx.HTTPTransport

#: Target modules read per metadata fetch (mapping modules read on demand).
DEFAULT_METADATA_MODULES: tuple[str, ...] = ("Leads", "Contacts", "Deals", "Accounts")

#: Record-search endpoint pattern (UNVERIFIED: needs experimental=True).
#: Doc: https://www.zoho.com/crm/developer/docs/api/v8/search-records.html
SEARCH_PATH = "/crm/v8/{module}/search"


def live_metadata(
    profile: str,
    *,
    modules: tuple[str, ...] = DEFAULT_METADATA_MODULES,
    max_api_calls: int | None = None,
    transport_factory: Callable[[], httpx.BaseTransport] | None = None,
) -> tuple[TargetMetadata, ZohoClient]:
    """Read field metadata for *modules* behind *profile* (GET-only, budgeted)."""
    current = load_profile(profile)
    budget = CallBudget(max_calls=max_api_calls or DEFAULT_MAX_API_CALLS)
    dc = DC_TABLE[current.dc]
    factory = transport_factory or TRANSPORT_FACTORY
    manager = TokenManager(dc=current.dc, profile=current.name, transport_factory=factory)
    client = authenticated_client(dc.api_base, manager, budget, factory())
    collected: dict[str, dict[str, FieldMeta]] = {}
    for module in modules:
        entries = unwrap_fields(
            read_model(
                client,
                "/crm/v8/settings/fields",
                FieldsResponse,
                params={"module": module},
            ).model_dump(),
            endpoint="/crm/v8/settings/fields",
        )
        collected[module] = {
            str(entry.get("api_name", "")): FieldMeta.from_entry(entry)
            for entry in entries
            if entry.get("api_name")
        }
    return TargetMetadata(modules=collected), client


def _live_client(
    profile: str,
    *,
    max_api_calls: int | None = None,
    transport_factory: Callable[[], httpx.BaseTransport] | None = None,
) -> tuple[ZohoClient, str]:
    """Shared authenticated GET-only client behind a named profile."""
    current = load_profile(profile)
    budget = CallBudget(max_calls=max_api_calls or DEFAULT_MAX_API_CALLS)
    dc = DC_TABLE[current.dc]
    factory = transport_factory or TRANSPORT_FACTORY
    manager = TokenManager(dc=current.dc, profile=current.name, transport_factory=factory)
    return authenticated_client(dc.api_base, manager, budget, factory()), current.name


def live_users(
    profile: str,
    *,
    max_api_calls: int | None = None,
    transport_factory: Callable[[], httpx.BaseTransport] | None = None,
) -> tuple[dict[str, str], ZohoClient]:
    """Read target users behind *profile*: normalized email -> status (TK-MIG-F7).

    Uses the verified ``/crm/v8/users`` endpoint (no ``--experimental``).
    """
    from zohokit.connectors.zoho.models import UsersResponse

    client, _ = _live_client(
        profile, max_api_calls=max_api_calls, transport_factory=transport_factory
    )
    page = read_model(client, "/crm/v8/users", UsersResponse)
    return users_from_envelope(page.model_dump()), client


def live_search_fn(client: ZohoClient) -> SearchFn:
    """Build the target-search closure over an authenticated client (TK-MIG-F5).

    The record-search endpoint is `unverified`, so every call passes
    ``experimental=True`` (the CLI requires ``--experimental`` to reach
    this path at all). Returned matches are fingerprints, never raw IDs.
    """

    def search(module: str, email: str | None, phone: str | None) -> list[str]:
        if email is not None:
            criteria = f"(Email:equals:{email})"
        elif phone is not None:
            criteria = f"(Phone:equals:{phone})"
        else:
            return []
        page = read_model(
            client,
            SEARCH_PATH.format(module=module),
            RecordPage,
            params={"criteria": criteria},
            experimental=True,
        )
        if not isinstance(page, RecordPage):  # pragma: no cover - model is fixed above
            raise ValueError("record search did not return a record page")
        return sorted(
            {
                target_fingerprint(str(record.get("id", "")))
                for record in page.data
                if record.get("id")
            }
        )

    return search


__all__: list[str] = [
    "DEFAULT_METADATA_MODULES",
    "SEARCH_PATH",
    "TRANSPORT_FACTORY",
    "live_metadata",
    "live_search_fn",
    "live_users",
]
