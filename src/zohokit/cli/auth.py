"""``zohokit auth``: Self Client login and status (STD-A1, TK-CONN-1)."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

import httpx
import typer

from zohokit.cli.common import fail
from zohokit.connectors.zoho.auth import (
    exchange_grant_code,
    read_client_secret,
    read_refresh_token,
    store_client_secret,
    store_refresh_token,
)
from zohokit.connectors.zoho.dc import DC_TABLE, data_centre
from zohokit.connectors.zoho.profiles import Profile, load_profile, save_profile

app = typer.Typer(help="Connect the toolkit to Zoho (read-only).")

#: Inner transport factory for the token exchange (tests inject a mock).
TRANSPORT_FACTORY: Callable[[], httpx.BaseTransport] = httpx.HTTPTransport


def _read_grant_code() -> str:
    """Read the pasted grant code from stdin, never from argv."""
    typer.echo("Paste the Self Client grant code, then press Enter.", err=True)
    code = sys.stdin.readline().strip()
    if not code:
        fail("no grant code on stdin: paste the code the Self Client issued")
    return code


@app.command()
def login(
    profile: Annotated[str, typer.Option("--profile", help="Profile name to create.")],
    dc: Annotated[str, typer.Option("--dc", help="Data centre: us/eu/in/au/jp/ca/cn.")],
    scopes: Annotated[str, typer.Option("--scopes", help="Comma-separated read scopes.")],
    env: Annotated[
        str,
        typer.Option("--env", help="Environment type: developer_edition/sandbox/trial/production."),
    ] = "developer_edition",
    org_name: Annotated[
        str, typer.Option("--org-name", help="Org display name (required for production).")
    ] = "",
) -> None:
    """Exchange a Self Client grant code and store the refresh token."""
    if env not in ("developer_edition", "sandbox", "trial", "production"):
        fail(f"unknown --env {env!r}")
    try:
        centre = data_centre(dc)
    except ValueError as exc:
        fail(str(exc))
    if env == "production" and not org_name:
        fail("production profiles require --org-name for the confirmation gate")
    requested = [scope.strip() for scope in scopes.split(",") if scope.strip()]
    if not requested:
        fail("pass at least one read scope via --scopes")
    client_id = os.environ.get("ZOHO_CLIENT_ID") or read_client_secret(profile, "client_id")
    client_secret = os.environ.get("ZOHO_CLIENT_SECRET") or read_client_secret(
        profile, "client_secret"
    )
    if not client_id or not client_secret:
        fail(
            "client id/secret not found: store them first "
            "(`zohokit auth store-client --profile NAME`) or set ZOHO_CLIENT_ID/ZOHO_CLIENT_SECRET"
        )
    code = _read_grant_code()
    transport = TRANSPORT_FACTORY()
    try:
        tokens = exchange_grant_code(
            code,
            dc=dc,
            client_id=client_id,
            client_secret=client_secret,
            transport=transport,
            expected_api_base=centre.api_base,
        )
    except Exception as exc:
        fail(f"token exchange failed: {exc}")
    store_refresh_token(profile, tokens.refresh_token)
    saved = save_profile(
        Profile(name=profile, dc=dc, scopes=requested, environment=env, org_name=org_name)  # type: ignore[arg-type]
    )
    typer.echo(f"Logged in profile {profile!r} (DC {dc}); refresh token stored. ({saved})")


@app.command(name="store-client")
def store_client(
    profile: Annotated[str, typer.Option("--profile", help="Profile name.")],
    client_id: Annotated[str | None, typer.Option("--client-id", help="Zoho client id.")] = None,
    client_secret: Annotated[
        str | None, typer.Option("--client-secret", help="Zoho client secret.")
    ] = None,
) -> None:
    """Store the client id/secret in the OS keyring (never in repo files)."""
    cid = client_id or os.environ.get("ZOHO_CLIENT_ID", "")
    secret = client_secret or os.environ.get("ZOHO_CLIENT_SECRET", "")
    if not cid or not secret:
        fail("pass --client-id/--client-secret or set ZOHO_CLIENT_ID/ZOHO_CLIENT_SECRET")
    store_client_secret(profile, "client_id", cid)
    store_client_secret(profile, "client_secret", secret)
    typer.echo(f"Stored client credentials for profile {profile!r} in the OS keyring.")


@app.command()
def status(
    profile: Annotated[str, typer.Option("--profile", help="Profile name.")],
) -> None:
    """Show profile, DC, scopes and token age — never a token or secret."""
    try:
        current = load_profile(profile)
    except ValueError as exc:
        fail(str(exc))
    stored = read_refresh_token(profile)
    saved_at = current.saved_at or "unknown"
    age = "unknown"
    if current.saved_at:
        try:
            saved = datetime.fromisoformat(current.saved_at)
            if saved.tzinfo is None:
                saved = saved.replace(tzinfo=UTC)
            seconds = (datetime.now(UTC) - saved).total_seconds()
            age = f"{int(seconds // 86400)}d {int((seconds % 86400) // 3600)}h"
        except ValueError:
            pass
    typer.echo(f"profile: {current.name}")
    typer.echo(f"dc: {current.dc} ({DC_TABLE[current.dc].accounts_host})")
    typer.echo(f"scopes: {', '.join(current.scopes)}")
    typer.echo(f"environment: {current.environment}")
    typer.echo(f"saved_at: {saved_at} (token age {age})")
    typer.echo(f"refresh_token: {'stored' if stored else 'missing'}")


__all__: list[str] = ["app"]
