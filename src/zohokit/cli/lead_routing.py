"""``zohokit lead-routing route`` (TK-MIG-4)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from zohokit.cli.common import (
    AiAfter,
    BaselineAfter,
    LiveAfter,
    MaxApiCallsAfter,
    ProfileAfter,
    emit,
    fresh_context,
    load_input,
    parse_model,
    reject_future_flags,
    resolve_runtime,
)
from zohokit.modules.lead_routing.engine import run
from zohokit.modules.lead_routing.models import LeadRoutingInput

app = typer.Typer(help="Route inbound leads without sending anything.")


@app.command()
def route(
    fixture: Annotated[Path, typer.Argument(help="JSON with inbound leads.")],
    input_format: Annotated[
        str | None, typer.Option("--input-format", help="Only legacy-v1.")
    ] = None,
    default_region: Annotated[
        str | None, typer.Option("--default-region", help="Explicit region, e.g. IN.")
    ] = None,
    strict: Annotated[bool, typer.Option("--strict", help="Exit 2 when not ready.")] = False,
    format_name: Annotated[
        str, typer.Option("--format", help="json|table|markdown|html.")
    ] = "json",
    out: Annotated[Path | None, typer.Option("--out", help="Write the report to a file.")] = None,
    live: LiveAfter = False,
    profile: ProfileAfter = None,
    ai: AiAfter = False,
    baseline: BaselineAfter = None,
    max_api_calls: MaxApiCallsAfter = None,
) -> None:
    """Route leads to queues; never merges, never sends."""
    reject_future_flags(live, profile, ai, baseline, max_api_calls)
    data = load_input(fixture, "lead_routing", input_format)
    report = run(
        parse_model(LeadRoutingInput, data), ctx=fresh_context(), default_region=default_region
    )
    runtime = resolve_runtime(format_name, out, strict=strict)
    emit(report, runtime.format_name, runtime.out, strict=runtime.strict)


__all__: list[str] = ["app"]
