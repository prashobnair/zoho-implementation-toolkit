"""``zohokit doctor``: read-only checklist for a profile (TK-CONN-2)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer

from zohokit.cli.common import fail
from zohokit.connectors.zoho.auth import TokenManager, read_refresh_token
from zohokit.connectors.zoho.budget import DEFAULT_MAX_API_CALLS, CallBudget
from zohokit.connectors.zoho.client import ZohoClient
from zohokit.connectors.zoho.dc import DC_TABLE
from zohokit.connectors.zoho.doctor import CheckResult, doctor_exit_code, run_doctor
from zohokit.connectors.zoho.profiles import load_profile

app = typer.Typer(help="Check a profile before any live read.")

#: Inner transport factory for API reads (tests inject a mock).
TRANSPORT_FACTORY: Callable[[], httpx.BaseTransport] = httpx.HTTPTransport


def render_json(profile_name: str, checks: list[CheckResult]) -> dict[str, Any]:
    """Checklist as a redaction-safe JSON document (fingerprints only, no IDs)."""
    current = load_profile(profile_name)
    return {
        "profile": current.name,
        "dc": current.dc,
        "environment": current.environment,
        "scopes": sorted(current.scopes),
        "checks": [
            {"name": check.name, "status": check.status, "detail": check.detail} for check in checks
        ],
        "exit_code": doctor_exit_code(checks),
    }


def render_table(checks: list[CheckResult]) -> str:
    """Redacted checklist table for the job log (fingerprints only, no secrets)."""
    return "".join(f"[{check.status.upper():4}] {check.name}: {check.detail}\n" for check in checks)


def render_markdown(profile_name: str, checks: list[CheckResult]) -> str:
    """Checklist as a short Markdown summary for the live-run evidence bundle."""
    lines = [f"# Doctor: {profile_name}", ""]
    for check in checks:
        mark = "PASS" if check.status == "pass" else check.status.upper()
        lines.append(f"- [{mark}] {check.name}: {check.detail}")
    lines.append("")
    return "\n".join(lines)


@app.callback(invoke_without_command=True)
def main(
    profile: Annotated[str | None, typer.Option("--profile", help="Profile to check.")] = None,
    max_api_calls: Annotated[
        int | None, typer.Option("--max-api-calls", help="Call budget (default 200).")
    ] = None,
    experimental: Annotated[
        bool, typer.Option("--experimental", help="Allow unverified endpoints.")
    ] = False,
    live: Annotated[
        bool, typer.Option("--live", help="Read from Zoho via the named profile.")
    ] = False,
    format_name: Annotated[
        str, typer.Option("--format", help="Output format: table, json or markdown.")
    ] = "table",
    out: Annotated[
        Path | None, typer.Option("--out", help="Write the report to this file.")
    ] = None,
    confirm_org: Annotated[
        str | None,
        typer.Option("--confirm-org", help="Org name confirmation (production only)."),
    ] = None,
) -> None:
    """Run the checklist; exit 3 on any fail."""
    if not live:
        fail("doctor reads from Zoho: pass --live --profile NAME (read-only, budget-capped)")
    if profile is None:
        fail("--live requires --profile: there is no default profile")
    if format_name not in ("table", "json", "markdown"):
        fail(f"unsupported --format {format_name!r} (table|json|markdown)")
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
    if format_name == "json":
        document = render_json(current.name, checks)
        text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    elif format_name == "markdown":
        text = render_markdown(current.name, checks)
    else:
        text = render_table(checks)
    if out is None:
        typer.echo(text.rstrip("\n"))
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        typer.echo(f"Wrote {out}")
        # Always leave the redacted checklist in the job log, even when the
        # machine-readable file goes to --out (fingerprints only, no secrets).
        table = text if format_name == "table" else render_table(checks)
        typer.echo(table.rstrip("\n"))
    raise typer.Exit(code=doctor_exit_code(checks))


__all__: list[str] = ["app"]
