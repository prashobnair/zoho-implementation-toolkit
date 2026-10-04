"""Typer CLI: ``zohokit <module> <command>`` (TK-X-1)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from typer._click import exceptions as _click_exceptions

from zohokit import __version__
from zohokit.cli import auth as auth_cli
from zohokit.cli import books as books_cli
from zohokit.cli import cache as cache_cli
from zohokit.cli import doctor as doctor_cli
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
    apply_baseline_file,
    check_unavailable_globals,
    ensure_utf8_stdio,
    fail,
    reject_future_flags,
    reject_unsupported_live,
    set_global_options,
)
from zohokit.core.diff_reports import (
    diff_reports,
    render_diff_json,
    render_diff_markdown,
    render_diff_table,
)
from zohokit.core.findings import Report
from zohokit.modules import MODULES
from zohokit.modules.plugins import discover_module_apps

# Windows consoles/pipes default to cp1252, which cannot encode the
# intentional "→" in release attribute diffs. Force UTF-8 at startup so
# redirected/piped output never raises UnicodeEncodeError (exit 1).
# Best-effort: no-op where streams lack reconfigure (e.g. test capture).
ensure_utf8_stdio()

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


def _load_report(path: Path) -> Report:
    """Read a report envelope; exit 1 with a value-free message on failure."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        fail(f"cannot read {path}: {exc.strerror or exc}")
    except ValueError:
        fail(f"{path} is not valid JSON")
    try:
        return Report.model_validate(raw)
    except ValueError:
        fail(f"{path} is not a zohokit report envelope")


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
    root.add_typer(auth_cli.app, name="auth")
    root.add_typer(doctor_cli.app, name="doctor")
    root.add_typer(cache_cli.app, name="cache")

    @root.callback()
    def _global_options(
        live: Annotated[
            bool, typer.Option("--live", help="Read from Zoho via a named profile.")
        ] = False,
        profile: Annotated[
            str | None,
            typer.Option("--profile", help="Named auth profile (see `zohokit auth login`)."),
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
            typer.Option("--baseline", help="Accepted-findings file (.zohokit-baseline.json)."),
        ] = None,
        max_api_calls: Annotated[
            int | None,
            typer.Option("--max-api-calls", help="API call budget per run (default 200)."),
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
        reject_unsupported_live("version", live, profile, max_api_calls)
        reject_future_flags(ai)
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
        reject_unsupported_live("modules list", live, profile, max_api_calls)
        reject_future_flags(ai)
        for name in available_modules():
            typer.echo(name)

    for plugin_name, plugin_app in discover_module_apps().items():
        root.add_typer(plugin_app, name=plugin_name)

    @root.command("diff-reports")
    def diff_reports_cmd(
        before: Annotated[Path, typer.Argument(help="Earlier report JSON.")],
        after: Annotated[Path, typer.Argument(help="Later report JSON.")],
        format_name: Annotated[str, typer.Option("--format", help="json|table|markdown.")] = "json",
        out: Annotated[Path | None, typer.Option("--out", help="Write the diff to a file.")] = None,
        strict: Annotated[
            bool, typer.Option("--strict", help="Exit 2 when new error findings exist.")
        ] = False,
        live: LiveAfter = False,
        profile: ProfileAfter = None,
        ai: AiAfter = False,
        baseline: BaselineAfter = None,
        max_api_calls: MaxApiCallsAfter = None,
    ) -> None:
        """Show new, resolved and changed findings between two reports."""
        reject_unsupported_live("diff-reports", live, profile, max_api_calls)
        reject_future_flags(ai)
        old_report = _load_report(before)
        new_report = _load_report(after)
        if baseline is not None:
            new_report = apply_baseline_file(new_report, baseline, now=datetime.now(UTC))
        diff = diff_reports(old_report, new_report)
        if format_name == "json":
            text = render_diff_json(old_report, new_report, diff)
        elif format_name == "table":
            text = render_diff_table(diff)
        elif format_name == "markdown":
            text = render_diff_markdown(old_report, new_report, diff)
        else:
            fail(f"unsupported --format {format_name!r} (json|table|markdown)")
        if out is None:
            typer.echo(text)
        else:
            out.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
            typer.echo(f"Wrote {out}")
        if strict and diff.new_errors:
            raise typer.Exit(code=2)

    return root


app = create_app()


def main() -> None:
    """Console-script entry point."""
    ensure_utf8_stdio()
    app()


__all__: list[str] = ["app", "available_modules", "create_app", "main"]
