"""``zohokit release diff`` (TK-MIG-4)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from zohokit.cli.common import emit, fresh_context, load_input, parse_model
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
        str, typer.Option("--format", help="json|table|markdown|html.")
    ] = "json",
    out: Annotated[Path | None, typer.Option("--out", help="Write the report to a file.")] = None,
) -> None:
    """Diff two manifests and report blocking changes."""
    data = load_input(fixture, "release", input_format)
    report = run(parse_model(ReleaseInput, data), ctx=fresh_context())
    emit(report, format_name, out, strict=strict)


__all__: list[str] = ["app"]
