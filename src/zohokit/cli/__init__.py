"""Typer CLI: ``zohokit <module> <command>`` (TK-X-1)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from typer._click import exceptions as _click_exceptions

from zohokit import __version__
from zohokit.cli import books as books_cli
from zohokit.cli import forms as forms_cli
from zohokit.cli import lead_routing as lead_routing_cli
from zohokit.cli import metrics as metrics_cli
from zohokit.cli import migration as migration_cli
from zohokit.cli import release as release_cli
from zohokit.cli import timeline as timeline_cli
from zohokit.cli import workflow as workflow_cli
from zohokit.cli.common import (
    AiAfter,
    BaselineAfter,
    GlobalOptions,
    LiveAfter,
    MaxApiCallsAfter,
    ProfileAfter,
    check_unavailable_globals,
    reject_future_flags,
    set_global_options,
)
from zohokit.modules import MODULES
from zohokit.modules.plugins import discover_module_apps

# STD §3.5: input/usage errors (unknown option, missing argument, bad
# value) exit 1. The framework default is 2, which would be
# indistinguishable from "blocked release" (--strict exit 2), so a CI
# gate could not tell a typo from a blocked release. Applied at import
# time so every entry point (console script, CliRunner) shares the
# contract. ``typer.Exit(code=2)`` from --strict blocking findings is a
# different class and is unaffected, as is ``--help`` (exit 0).
_click_exceptions.UsageError.exit_code = 1


def available_modules() -> list[str]:
    """Built-in modules in canonical order, then third-party plugin names."""
    return [*MODULES, *sorted(discover_module_apps())]


def create_app() -> typer.Typer:
    """Build the CLI: built-ins plus entry-point plugins (TK-ARCH-4)."""
    root = typer.Typer(help="An implementation engineer's safety kit for Zoho.")
    modules_app = typer.Typer(help="Inspect available modules.")
    root.add_typer(modules_app, name="modules")
    root.add_typer(migration_cli.app, name="migration")
    root.add_typer(release_cli.app, name="release")
    root.add_typer(workflow_cli.app, name="workflow")
    root.add_typer(forms_cli.app, name="forms")
    root.add_typer(books_cli.app, name="books")
    root.add_typer(metrics_cli.app, name="metrics")
    root.add_typer(timeline_cli.app, name="timeline")
    root.add_typer(lead_routing_cli.app, name="lead-routing")

    @root.callback()
    def _global_options(
        live: Annotated[
            bool, typer.Option("--live", help="Read from Zoho (not available until v0.2.0).")
        ] = False,
        profile: Annotated[
            str | None,
            typer.Option("--profile", help="Named auth profile (not available until v0.2.0)."),
        ] = None,
        format_name: Annotated[
            str | None,
            typer.Option("--format", help="Default report format for every command."),
        ] = None,
        out: Annotated[
            Path | None,
            typer.Option("--out", help="Default report file for every command."),
        ] = None,
        strict: Annotated[
            bool, typer.Option("--strict", help="Exit 2 on blocking findings, every command.")
        ] = False,
        ai: Annotated[
            bool, typer.Option("--ai", help="AI assistance (not available until v0.3.0).")
        ] = False,
        baseline: Annotated[
            Path | None,
            typer.Option("--baseline", help="Suppression file (not available until v0.2.0)."),
        ] = None,
        max_api_calls: Annotated[
            int | None,
            typer.Option("--max-api-calls", help="API call budget (not available until v0.2.0)."),
        ] = None,
    ) -> None:
        """Shared flags. Unavailable features fail loudly, before any command."""
        options = GlobalOptions(
            live=live,
            profile=profile,
            format_name=format_name,
            out=out,
            strict=strict,
            ai=ai,
            baseline=baseline,
            max_api_calls=max_api_calls,
        )
        set_global_options(options)
        check_unavailable_globals(options)

    @root.command()
    def version(
        live: LiveAfter = False,
        profile: ProfileAfter = None,
        ai: AiAfter = False,
        baseline: BaselineAfter = None,
        max_api_calls: MaxApiCallsAfter = None,
    ) -> None:
        """Print the package version."""
        reject_future_flags(live, profile, ai, baseline, max_api_calls)
        typer.echo(__version__)

    @modules_app.command("list")
    def modules_list(
        live: LiveAfter = False,
        profile: ProfileAfter = None,
        ai: AiAfter = False,
        baseline: BaselineAfter = None,
        max_api_calls: MaxApiCallsAfter = None,
    ) -> None:
        """List the available toolkit modules, including plugins."""
        reject_future_flags(live, profile, ai, baseline, max_api_calls)
        for name in available_modules():
            typer.echo(name)

    for plugin_name, plugin_app in discover_module_apps().items():
        root.add_typer(plugin_app, name=plugin_name)
    return root


app = create_app()


def main() -> None:
    """Console-script entry point."""
    app()


__all__: list[str] = ["app", "available_modules", "create_app", "main"]
