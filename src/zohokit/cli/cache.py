"""``zohokit cache``: inspect and purge the GET response cache (STD-L6)."""

from __future__ import annotations

import typer

from zohokit.connectors.zoho.cache import ResponseCache

app = typer.Typer(help="Manage the on-disk response cache.")


@app.command()
def purge() -> None:
    """Remove every cached response."""
    removed = ResponseCache().purge()
    typer.echo(f"Purged {removed} cached response(s).")


@app.command()
def dir() -> None:
    """Print where cached responses live."""
    typer.echo(str(ResponseCache().directory))


__all__: list[str] = ["app"]
