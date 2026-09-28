"""``zohokit timeline compose`` (TK-MIG-4)."""

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
    fail,
    fresh_context,
    load_input,
    parse_model,
    reject_future_flags,
    resolve_runtime,
)
from zohokit.modules.timeline.engine import run
from zohokit.modules.timeline.models import TimelineInput

app = typer.Typer(help="Compose a client-safe timeline with contradiction review.")


@app.command()
def compose(
    fixture: Annotated[Path, typer.Argument(help="JSON with account events.")],
    input_format: Annotated[
        str | None, typer.Option("--input-format", help="Only legacy-v1.")
    ] = None,
    audience: Annotated[str, typer.Option("--audience", help="internal|client.")] = "internal",
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
    """Compose events chronologically and flag claim contradictions."""
    reject_future_flags(live, profile, ai, baseline, max_api_calls)
    if audience not in {"internal", "client"}:
        fail(f"unsupported --audience {audience!r} (internal|client)")
    data = load_input(fixture, "timeline", input_format)
    report = run(parse_model(TimelineInput, data), ctx=fresh_context(), audience=audience)
    runtime = resolve_runtime(format_name, out, strict=strict)
    emit(report, runtime.format_name, runtime.out, strict=runtime.strict)


__all__: list[str] = ["app"]
