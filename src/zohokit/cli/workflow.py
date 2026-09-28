"""``zohokit workflow simulate`` (TK-MIG-4)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from zohokit.cli.common import emit, fresh_context, load_input, parse_model, resolve_runtime
from zohokit.modules.workflow.engine import run
from zohokit.modules.workflow.models import WorkflowInput

app = typer.Typer(help="Trace workflow rules over a record.")


@app.command()
def simulate(
    fixture: Annotated[Path, typer.Argument(help="JSON with rules and a record.")],
    input_format: Annotated[
        str | None, typer.Option("--input-format", help="Only legacy-v1.")
    ] = None,
    strict: Annotated[bool, typer.Option("--strict", help="Exit 2 when findings remain.")] = False,
    format_name: Annotated[
        str, typer.Option("--format", help="json|table|markdown|html.")
    ] = "json",
    out: Annotated[Path | None, typer.Option("--out", help="Write the report to a file.")] = None,
) -> None:
    """Simulate rules against one record and report the trace."""
    data = load_input(fixture, "workflow", input_format)
    report = run(parse_model(WorkflowInput, data), ctx=fresh_context())
    runtime = resolve_runtime(format_name, out, strict=strict)
    emit(report, runtime.format_name, runtime.out, strict=runtime.strict)


__all__: list[str] = ["app"]
