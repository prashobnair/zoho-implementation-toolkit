"""``zohokit migration audit`` (TK-MIG-4)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from zohokit.cli.common import emit, fresh_context, load_input, parse_model
from zohokit.modules.migration.engine import run
from zohokit.modules.migration.models import MigrationInput

app = typer.Typer(help="Audit a CRM migration source before import.")


@app.command()
def audit(
    fixture: Annotated[Path, typer.Argument(help="JSON export (legacy-v1 envelope).")],
    input_format: Annotated[
        str | None, typer.Option("--input-format", help="Only legacy-v1.")
    ] = None,
    strict: Annotated[bool, typer.Option("--strict", help="Exit 2 when not ready.")] = False,
    format_name: Annotated[
        str, typer.Option("--format", help="json|table|markdown|html.")
    ] = "json",
    out: Annotated[Path | None, typer.Option("--out", help="Write the report to a file.")] = None,
) -> None:
    """Audit a source export and report what would break on import."""
    data = load_input(fixture, "migration", input_format)
    report = run(parse_model(MigrationInput, data), ctx=fresh_context())
    emit(report, format_name, out, strict=strict)


__all__: list[str] = ["app"]
