"""``zohokit metrics check`` (TK-MIG-4)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from zohokit.cli.common import emit, fail, fresh_context, load_input, parse_model
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
        str, typer.Option("--format", help="json|table|markdown|html.")
    ] = "json",
    out: Annotated[Path | None, typer.Option("--out", help="Write the report to a file.")] = None,
) -> None:
    """Evaluate metric contracts for one audience."""
    if audience not in {"sales", "finance", "operations"}:
        fail(f"unsupported --audience {audience!r} (sales|finance|operations)")
    data = load_input(fixture, "metrics", input_format)
    report = run(parse_model(MetricsInput, data), ctx=fresh_context(), audience=audience)
    emit(report, format_name, out, strict=strict)


__all__: list[str] = ["app"]
