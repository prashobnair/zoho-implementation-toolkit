"""``zohokit doctor``: read-only checklist for a profile (TK-CONN-2)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

import httpx
import typer

from zohokit.cli.common import fail
from zohokit.connectors.zoho.auth import TokenManager, read_refresh_token
from zohokit.connectors.zoho.budget import DEFAULT_MAX_API_CALLS, CallBudget
from zohokit.connectors.zoho.client import ZohoClient
from zohokit.connectors.zoho.dc import DC_TABLE
from zohokit.connectors.zoho.doctor import doctor_exit_code, run_doctor
from zohokit.connectors.zoho.profiles import load_profile

app = typer.Typer(help="Check a profile before any live read.")

#: Inner transport factory for API reads (tests inject a mock).
TRANSPORT_FACTORY: Callable[[], httpx.BaseTransport] = httpx.HTTPTransport


@app.callback(invoke_without_command=True)
def main(
    profile: Annotated[str | None, typer.Option("--profile", help="Profile to check.")] = None,
    max_api_calls: Annotated[
        int | None, typer.Option("--max-api-calls", help="Call budget (default 200).")
    ] = None,
    experimental: Annotated[
        bool, typer.Option("--experimental", help="Allow unverified endpoints.")
    ] = False,
    confirm_org: Annotated[
        str | None,
        typer.Option("--confirm-org", help="Org name confirmation (production only)."),
    ] = None,
) -> None:
    """Run the checklist; exit 3 on any fail."""
    if profile is None:
        fail("--live requires --profile: there is no default profile")
    try:
        current = load_profile(profile)
    except ValueError as exc:
        fail(str(exc))
    budget = CallBudget(max_calls=max_api_calls or DEFAULT_MAX_API_CALLS)
    dc = DC_TABLE[current.dc]

    def make_client() -> ZohoClient:
        manager = TokenManager(
            dc=current.dc, profile=current.name, transport_factory=TRANSPORT_FACTORY
        )
        return ZohoClient(
            dc.api_base,
            transport=TRANSPORT_FACTORY(),
            token_provider=manager.token_provider,
            budget=budget,
        )

    def refresher() -> bool:
        return bool(read_refresh_token(current.name))

    checks = run_doctor(
        current,
        client_factory=make_client,
        token_refresher=refresher,
        budget=budget,
        confirmed_org_name=confirm_org,
        experimental=experimental,
    )
    for check in checks:
        typer.echo(f"[{check.status.upper():4}] {check.name}: {check.detail}")
    raise typer.Exit(code=doctor_exit_code(checks))


__all__: list[str] = ["app"]
