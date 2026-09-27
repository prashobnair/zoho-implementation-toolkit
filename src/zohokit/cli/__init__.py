"""Typer CLI: ``zohokit <module> <command>`` (TK-X-1 scaffold)."""

from __future__ import annotations

import typer

from zohokit import __version__
from zohokit.cli import forms as forms_cli
from zohokit.cli import migration as migration_cli
from zohokit.cli import release as release_cli
from zohokit.cli import workflow as workflow_cli
from zohokit.modules import MODULES

app = typer.Typer(help="An implementation engineer's safety kit for Zoho.")
modules_app = typer.Typer(help="Inspect available modules.")
app.add_typer(modules_app, name="modules")
app.add_typer(migration_cli.app, name="migration")
app.add_typer(release_cli.app, name="release")
app.add_typer(workflow_cli.app, name="workflow")
app.add_typer(forms_cli.app, name="forms")


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@modules_app.command("list")
def modules_list() -> None:
    """List the available toolkit modules."""
    for name in MODULES:
        typer.echo(name)


def main() -> None:
    """Console-script entry point."""
    app()


__all__: list[str] = ["app", "main"]
