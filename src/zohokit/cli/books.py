"""``zohokit books reconcile`` (TK-MIG-4)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from zohokit.cli.common import emit, fresh_context, load_input, parse_model
from zohokit.modules.books.engine import run
from zohokit.modules.books.models import BooksInput

app = typer.Typer(help="Reconcile Books invoices against CRM deals.")


@app.command()
def reconcile(
    fixture: Annotated[Path, typer.Argument(help="JSON with entities, deals, invoices.")],
    input_format: Annotated[
        str | None, typer.Option("--input-format", help="Only legacy-v1.")
    ] = None,
    strict: Annotated[bool, typer.Option("--strict", help="Exit 2 when not ready.")] = False,
    format_name: Annotated[
        str, typer.Option("--format", help="json|table|markdown|html.")
    ] = "json",
    out: Annotated[Path | None, typer.Option("--out", help="Write the report to a file.")] = None,
) -> None:
    """Reconcile every deal against its invoices and report mismatches."""
    data = load_input(fixture, "books", input_format)
    report = run(parse_model(BooksInput, data), ctx=fresh_context())
    emit(report, format_name, out, strict=strict)


__all__: list[str] = ["app"]
