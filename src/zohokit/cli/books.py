"""``zohokit books reconcile`` (TK-MIG-4, TK-BK-F1..F8)."""

from __future__ import annotations

import calendar
import re
from datetime import date
from pathlib import Path
from typing import Annotated, Any

import typer

from zohokit.cli.common import (
    AiAfter,
    BaselineAfter,
    LiveAfter,
    MaxApiCallsAfter,
    ProfileAfter,
    apply_baseline_file,
    emit,
    fail,
    fresh_context,
    load_input,
    parse_model,
    reject_future_flags,
    resolve_runtime,
)
from zohokit.modules.books.engine import run
from zohokit.modules.books.entities import (
    EntityMapConfigError,
    load_entity_map,
    resolve_org_ids,
)
from zohokit.modules.books.fx import FxConfigError, FxRate, load_fx_rates
from zohokit.modules.books.models import BooksInput
from zohokit.modules.books.policy import MatchPolicy, PolicyConfigError, load_policy

app = typer.Typer(help="Reconcile Books invoices against CRM deals.")

_PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})$")


def _resolve_period(value: str | None, policy: MatchPolicy) -> MatchPolicy:
    """Override the policy window from ``--period YYYY-MM`` (exit 1 if bad)."""
    if value is None:
        return policy
    match = _PERIOD_RE.match(value)
    if not match:
        fail(f"--period must be YYYY-MM, got {value!r}")
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        fail(f"--period must be YYYY-MM, got {value!r}")
    last = calendar.monthrange(year, month)[1]
    window = {
        "by": policy.period.by if policy.period else "deal_closing_date",
        "start": date(year, month, 1),
        "end": date(year, month, last),
    }
    try:
        return policy.model_copy(update={"period": window})
    except Exception as exc:
        fail(f"invalid --period {value!r}: {exc}")
    raise AssertionError("unreachable")


@app.command()
def reconcile(
    fixture: Annotated[Path, typer.Argument(help="JSON with entities, deals, invoices.")],
    input_format: Annotated[
        str | None,
        typer.Option("--input-format", help="legacy-v1 (golden envelope) or recon-v2."),
    ] = None,
    strict: Annotated[bool, typer.Option("--strict", help="Exit 2 when not ready.")] = False,
    format_name: Annotated[
        str, typer.Option("--format", help="json|table|markdown|html|sarif|junit|xlsx.")
    ] = "json",
    out: Annotated[Path | None, typer.Option("--out", help="Write the report to a file.")] = None,
    live: LiveAfter = False,
    profile: ProfileAfter = None,
    ai: AiAfter = False,
    baseline: BaselineAfter = None,
    max_api_calls: MaxApiCallsAfter = None,
    policy: Annotated[
        Path | None, typer.Option("--policy", help="Match-policy YAML (v2 recon).")
    ] = None,
    entity_map: Annotated[
        Path | None, typer.Option("--entity-map", help="Entity-map YAML (v2 recon).")
    ] = None,
    fx_rates: Annotated[
        Path | None, typer.Option("--fx-rates", help="FX-rate CSV (fx_rates.csv).")
    ] = None,
    period: Annotated[
        str | None, typer.Option("--period", help="Month window YYYY-MM (v2 recon).")
    ] = None,
    books_orgs: Annotated[
        str | None, typer.Option("--books-orgs", help="Comma-separated entity keys (live).")
    ] = None,
    unavailable: Annotated[
        str | None,
        typer.Option("--unavailable", help="Comma-separated entity keys treated as unreachable."),
    ] = None,
    experimental: Annotated[
        bool, typer.Option("--experimental", help="Allow unverified Books endpoints (live).")
    ] = False,
) -> None:
    """Reconcile every deal against its invoices and report mismatches."""
    from zohokit.modules.books.reconcile import run_recon

    wants_v2 = any(
        [
            policy is not None,
            entity_map is not None,
            fx_rates is not None,
            period is not None,
            books_orgs is not None,
            unavailable is not None,
            live,
            profile is not None,
            max_api_calls is not None,
            experimental,
        ]
    )
    if not wants_v2:
        reject_future_flags(ai, baseline)
        if input_format == "recon-v2":
            fail("recon-v2 input needs --policy and --entity-map (v2 recon)")
        data = load_input(fixture, "books", input_format or "legacy-v1")
        ctx = fresh_context()
        report = run(parse_model(BooksInput, data), ctx=ctx)
        report = apply_baseline_file(report, baseline, now=ctx.now)
        runtime = resolve_runtime(format_name, out, strict=strict)
        emit(report, runtime.format_name, runtime.out, strict=runtime.strict)

    reject_future_flags(ai, baseline)
    try:
        active_policy = load_policy(policy) if policy else MatchPolicy()
    except PolicyConfigError as exc:
        fail(str(exc))
    active_policy = _resolve_period(period, active_policy)
    if entity_map is None:
        fail("v2 recon needs --entity-map (entity key -> org ref, currency, criteria)")
    try:
        entities = load_entity_map(entity_map)
    except EntityMapConfigError as exc:
        fail(str(exc))
    rates: tuple[FxRate, ...] = ()
    if fx_rates is not None:
        try:
            rates = load_fx_rates(fx_rates)
        except FxConfigError as exc:
            fail(str(exc))
    data = load_input(fixture, "books", input_format)
    deals = data.get("deals", [])
    invoices = data.get("invoices", [])
    credit_notes = data.get("credit_notes", [])
    unavailable_keys = tuple(
        sorted({part.strip() for part in (unavailable or "").split(",") if part.strip()})
    )
    org_ids: dict[str, str] = {}
    if live or profile is not None or max_api_calls is not None or books_orgs is not None:
        if not live:
            fail("live reads need --live --profile NAME (read-only, budget-capped)")
        if not profile:
            fail("--live requires --profile: there is no default profile")
        if not experimental:
            fail("Books endpoints are unverified: live recon needs --experimental")
        if not books_orgs:
            fail("--live recon needs --books-orgs (comma-separated entity keys)")
        from zohokit.connectors.zoho.errors import ConnectorError, ContractDriftError
        from zohokit.connectors.zoho.profiles import load_profile
        from zohokit.modules.books.live import live_pull, live_pull_deals

        try:
            current = load_profile(profile)
        except ValueError as exc:
            fail(str(exc))
        wanted = [part.strip() for part in books_orgs.split(",") if part.strip()]
        unknown = [key for key in wanted if key not in entities]
        if unknown:
            fail(f"unknown entity keys: {', '.join(sorted(unknown))}")
        try:
            wanted_orgs = resolve_org_ids(
                {key: entities[key] for key in wanted}, dict(current.books_orgs)
            )
        except EntityMapConfigError as exc:
            fail(str(exc))
        try:
            bundles, failed = live_pull(profile, wanted_orgs, max_api_calls=max_api_calls or 200)
        except ValueError as exc:
            fail(str(exc))
        live_invoices: list[dict[str, Any]] = []
        live_credit_notes: list[dict[str, Any]] = []
        for key in wanted:
            if key in bundles:
                live_invoices.extend(bundles[key]["invoices"])
                live_credit_notes.extend(bundles[key]["credit_notes"])
        invoices = live_invoices
        credit_notes = live_credit_notes
        # CRM Deals stay live too (UC-BK-1): the fixture file path is
        # kept as the offline input (parsed above for its envelope), but
        # its deals are replaced by the CRM read.
        plan_field_name = (
            active_policy.allow_multiple_invoices_when.billing_plan_field
            if active_policy.allow_multiple_invoices_when
            else ""
        )
        policy_period = active_policy.period
        try:
            deals = live_pull_deals(
                profile,
                entities,
                active_policy.crm_fields,
                period_by=policy_period.by if policy_period else None,
                period_start=policy_period.start if policy_period else None,
                period_end=policy_period.end if policy_period else None,
                billing_plan_field=plan_field_name,
                max_api_calls=max_api_calls or 200,
            )
        except ValueError as exc:
            fail(str(exc))
        except (ConnectorError, ContractDriftError) as exc:
            typer.echo(f"Connector error: {exc}", err=True)
            raise typer.Exit(code=3) from exc
        unavailable_keys = tuple(sorted(set(unavailable_keys) | set(failed)))
        org_ids = wanted_orgs
    ctx = fresh_context()
    try:
        report = run_recon(
            {"deals": deals, "invoices": invoices, "credit_notes": credit_notes},
            policy=active_policy,
            entities=entities,
            org_ids=org_ids,
            fx_rates=rates,
            unavailable=unavailable_keys,
            ctx=ctx,
        )
    except ValueError as exc:
        fail(str(exc))
    report = apply_baseline_file(report, baseline, now=ctx.now)
    runtime = resolve_runtime(format_name, out, strict=strict)
    emit(report, runtime.format_name, runtime.out, strict=runtime.strict)


__all__: list[str] = ["app"]
