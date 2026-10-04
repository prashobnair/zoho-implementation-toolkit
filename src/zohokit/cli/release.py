"""``zohokit release diff`` (TK-MIG-4)."""

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
    fresh_context,
    load_input,
    parse_model,
    reject_future_flags,
    reject_unsupported_live,
    resolve_runtime,
)
from zohokit.core.plan import Plan, write_bundle
from zohokit.modules.release.engine import run
from zohokit.modules.release.models import ReleaseInput

app = typer.Typer(help="Diff sandbox vs production config manifests.")


@app.command()
def diff(
    fixture: Annotated[Path, typer.Argument(help="JSON with before/after manifests.")],
    input_format: Annotated[
        str | None, typer.Option("--input-format", help="Only legacy-v1.")
    ] = None,
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
    plan_out: Annotated[
        Path | None, typer.Option("--plan-out", help="Write a signed plan bundle here.")
    ] = None,
) -> None:
    """Diff two manifests and report blocking changes."""
    reject_unsupported_live("release", live, profile, max_api_calls)
    reject_future_flags(ai, baseline)
    data = load_input(fixture, "release", input_format)
    ctx = fresh_context()
    report = run(parse_model(ReleaseInput, data), ctx=ctx)
    report = apply_baseline_file(report, baseline, now=ctx.now)
    if plan_out is not None:
        json_path, _ = write_bundle(
            Plan(),
            plan_out,
            note=(
                "Offline diff proposes no writes to Zoho. "
                "A future live promotion would list its calls here for review."
            ),
        )
        typer.echo(f"Wrote {json_path}")
    runtime = resolve_runtime(format_name, out, strict=strict)
    emit(report, runtime.format_name, runtime.out, strict=runtime.strict)


__all__: list[str] = ["app"]
