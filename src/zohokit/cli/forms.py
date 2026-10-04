"""``zohokit forms parity`` (TK-MIG-4)."""

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
from zohokit.modules.forms.engine import run
from zohokit.modules.forms.models import FormsInput

app = typer.Typer(help="Prove a rebuilt form behaves like the original.")


@app.command()
def parity(
    fixture: Annotated[Path, typer.Argument(help="JSON with source/target fields and cases.")],
    input_format: Annotated[
        str | None, typer.Option("--input-format", help="Only legacy-v1.")
    ] = None,
    strict: Annotated[bool, typer.Option("--strict", help="Exit 2 when cases differ.")] = False,
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
    """Compare source and target form outputs over the answer cases."""
    reject_unsupported_live("forms", live, profile, max_api_calls)
    reject_future_flags(ai, baseline)
    data = load_input(fixture, "forms", input_format)
    ctx = fresh_context()
    report = run(parse_model(FormsInput, data), ctx=ctx)
    report = apply_baseline_file(report, baseline, now=ctx.now)
    runtime = resolve_runtime(format_name, out, strict=strict)
    emit(report, runtime.format_name, runtime.out, strict=runtime.strict)


__all__: list[str] = ["app"]
