"""Live snapshot reads for the release module (TK-REL-2, TK-REL-10).

Profile handling mirrors ``doctor``: named profile, no default, budget
cap, injectable transport for tests. All reads are GET-only through
the shared client; only verified endpoints are called.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from zohokit.connectors.zoho.auth import TokenManager
from zohokit.connectors.zoho.budget import DEFAULT_MAX_API_CALLS, CallBudget
from zohokit.connectors.zoho.client import ZohoClient
from zohokit.connectors.zoho.dc import DC_TABLE
from zohokit.connectors.zoho.profiles import load_profile
from zohokit.connectors.zoho.readers import authenticated_client
from zohokit.modules.release.manifest import Component, Manifest
from zohokit.modules.release.snapshot import DEFAULT_SNAPSHOT_MODULES, snapshot_from_client

#: Inner transport factory for API reads (tests inject a mock).
TRANSPORT_FACTORY: Callable[[], httpx.BaseTransport] = httpx.HTTPTransport


def live_snapshot(
    profile: str,
    *,
    modules: tuple[str, ...] = DEFAULT_SNAPSHOT_MODULES,
    extra: list[Component] | None = None,
    max_api_calls: int | None = None,
    transport_factory: Callable[[], httpx.BaseTransport] | None = None,
) -> tuple[Manifest, ZohoClient]:
    """Snapshot the org behind *profile*; return the manifest and client."""
    current = load_profile(profile)
    budget = CallBudget(max_calls=max_api_calls or DEFAULT_MAX_API_CALLS)
    dc = DC_TABLE[current.dc]
    factory = transport_factory or TRANSPORT_FACTORY
    manager = TokenManager(dc=current.dc, profile=current.name, transport_factory=factory)
    client = authenticated_client(dc.api_base, manager, budget, factory())
    manifest = snapshot_from_client(client, source_env=current.name, modules=modules, extra=extra)
    return manifest, client


__all__: list[str] = ["TRANSPORT_FACTORY", "live_snapshot"]
