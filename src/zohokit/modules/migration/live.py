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
from zohokit.connectors.zoho.models import FieldsResponse, unwrap_fields
from zohokit.connectors.zoho.profiles import load_profile
from zohokit.connectors.zoho.readers import authenticated_client, read_model
from zohokit.modules.migration.metadata import FieldMeta, TargetMetadata

#: Inner transport factory for API reads (tests inject a mock).
TRANSPORT_FACTORY: Callable[[], httpx.BaseTransport] = httpx.HTTPTransport

#: Target modules read per metadata fetch (mapping modules Pierced on demand).
DEFAULT_METADATA_MODULES: tuple[str, ...] = ("Leads", "Contacts", "Deals", "Accounts")


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


__all__: list[str] = ["DEFAULT_METADATA_MODULES", "TRANSPORT_FACTORY", "live_metadata"]
