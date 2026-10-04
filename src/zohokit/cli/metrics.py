"""``zohokit metrics check`` (TK-MIG-4)."""

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
    apply_baseline_file,
    emit,
    fail,
    fresh_context,
    load_input,
    parse_model,
    reject_future_flags,
    reject_unsupported_live,
    resolve_runtime,
)
from zohokit.modules.metrics.engine import run
from zohokit.modules.metrics.models import MetricsInput

app = typer.Typer(help="Check metric contracts over CRM/Books/People data.")


@app.command()
def check(
    fixture: Annotated[Path, typer.Argument(help="JSON tables plus freshness markers.")],
    input_format: Annotated[
        str | None, typer.Option("--input-format", help="Only legacy-v1.")
    ] = None,
    audience: Annotated[
        str, typer.Option("--audience", help="sales|finance|operations.")
    ] = "finance",
    strict: Annotated[bool, typer.Option("--strict", help="Exit 2 when not ready.")] = False,
    format_name: Annotated[
        str, typer.Option("--format", help="json|table|markdown|html|sarif|junit.")
    ] = "json",
    out: Annotated[Path | None, typer.Option("--out", help="Write the report to a file.")] = None,
    live: LiveAfter = False,
    profile: ProfileAfter = None,
    ai: AiAfter = False,
    baseline: BaselineAfter = None,
    max_api_calls: MaxApiCallsAfter = None,
) -> None:
    """Evaluate metric contracts for one audience."""
    reject_unsupported_live("metrics", live, profile, max_api_calls)
    reject_future_flags(ai, baseline)
    if audience not in {"sales", "finance", "operations"}:
        fail(f"unsupported --audience {audience!r} (sales|finance|operations)")
    data = load_input(fixture, "metrics", input_format)
    ctx = fresh_context()
    report = run(parse_model(MetricsInput, data), ctx=ctx, audience=audience)
    report = apply_baseline_file(report, baseline, now=ctx.now)
    runtime = resolve_runtime(format_name, out, strict=strict)
    emit(report, runtime.format_name, runtime.out, strict=runtime.strict)


__all__: list[str] = ["app"]
