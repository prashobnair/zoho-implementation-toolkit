"""Shared CLI plumbing: input loading, rendering, exit codes (TK-MIG-4)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, NoReturn, TypeAlias, TypeVar

import typer
from pydantic import BaseModel, ValidationError

from zohokit.cli.exitcodes import resolve
from zohokit.core.baseline import BaselineError, apply_baseline, load_baseline
from zohokit.core.context import RunContext
from zohokit.core.findings import Report
from zohokit.reports import (
    render_html,
    render_json,
    render_junit,
    render_markdown,
    render_sarif,
    render_table,
)

ModelT = TypeVar("ModelT", bound=BaseModel)

LEGACY_MARKERS: dict[str, set[str]] = {
    "migration": {"organizations", "people", "deals", "activities"},
    "release": {"before", "after"},
    "workflow": {"rules", "record"},
    "forms": {"source_fields", "target_fields", "cases"},
    "books": {"entities", "deals", "invoices"},
    "metrics": {"accounts", "deals", "invoices", "staff"},
    "timeline": {"events"},
    "lead_routing": {"leads"},
}

_RENDERERS = {
    "json": render_json,
    "table": render_table,
    "markdown": render_markdown,
    "html": render_html,
    "sarif": render_sarif,
    "junit": render_junit,
}

#: Accepted ``--format`` values, shared by every command's help text.
FORMATS_HELP = "json|table|markdown|html|sarif|junit."


def fail(message: str) -> NoReturn:
    """Exit 1 with a usage/input error (STD §3.5)."""
    typer.echo(f"Input error: {message}", err=True)
    raise typer.Exit(code=1)


@dataclass(frozen=True)
class GlobalOptions:
    """Root-level flags shared by every command (TK-X-1).

    ``live``, ``profile`` and ``max_api_calls`` are honored by the
    ``auth``, ``doctor`` and ``cache`` commands; per-module live reads are
    not wired yet, so module commands refuse them loudly instead of
    silently ignoring them. ``ai`` names a feature that does not exist
    yet; using it fails loudly (exit 1). ``baseline`` applies an
    accepted-findings file. ``format_name``, ``out`` and ``strict`` act
    as defaults when the command does not set them.
    """

    live: bool = False
    profile: str | None = None
    format_name: str | None = None
    out: Path | None = None
    strict: bool = False
    ai: bool = False
    baseline: Path | None = None
    max_api_calls: int | None = None


_GLOBAL = GlobalOptions()


# After-subcommand spellings of the root flags (TK-X-1).
#
# Click only accepts root options *before* the subcommand, so every leaf
# command re-declares these flags with identical help text. ``--ai`` names
# a feature that does not exist yet and always fails loudly.
# ``--baseline`` applies an accepted-findings file. ``--live``/``--profile``/
# ``--max-api-calls`` are honored by the auth, doctor and cache commands;
# every other command refuses them loudly (see :func:`reject_unsupported_live`)
# until its live path is wired.
LiveAfter: TypeAlias = Annotated[
    bool, typer.Option("--live", help="Read from Zoho via a named profile.")
]
ProfileAfter: TypeAlias = Annotated[
    str | None,
    typer.Option("--profile", help="Named auth profile (see `zohokit auth login`)."),
]
AiAfter: TypeAlias = Annotated[
    bool, typer.Option("--ai", help="AI assistance (not available until v0.3.0).")
]
BaselineAfter: TypeAlias = Annotated[
    Path | None,
    typer.Option("--baseline", help="Accepted-findings file (.zohokit-baseline.json)."),
]
MaxApiCallsAfter: TypeAlias = Annotated[
    int | None,
    typer.Option("--max-api-calls", help="API call budget per run (default 200)."),
]


def reject_future_flags(
    ai: bool = False,
    baseline: Path | None = None,
) -> None:
    """Fail loudly when an after-subcommand flag names a missing feature.

    Only ``--ai`` is still gated here. ``--baseline`` is accepted by every
    command that produces a report; the parameter stays so existing call
    sites keep working while each command wires it to
    :func:`apply_baseline_file`.
    """
    check_unavailable_globals(GlobalOptions(ai=ai))
    _ = baseline


def reject_unsupported_live(
    module: str,
    live: bool = False,
    profile: str | None = None,
    max_api_calls: int | None = None,
) -> None:
    """Refuse live flags on module commands whose live path is not wired yet.

    Checks both the before-subcommand root flags and the after-subcommand
    spellings, so neither position can slip through silently.
    """
    root = _GLOBAL.live or _GLOBAL.profile is not None or _GLOBAL.max_api_calls is not None
    if root or live or profile is not None or max_api_calls is not None:
        fail(
            f"Live reads are not available for `{module}` yet. "
            "This run touched no network. "
            "Use `zohokit auth login`, `zohokit doctor` and `zohokit cache` for now."
        )


def set_global_options(options: GlobalOptions) -> None:
    """Record the root flags for this invocation (called by the CLI callback)."""
    global _GLOBAL
    _GLOBAL = options


def check_unavailable_globals(options: GlobalOptions | None = None) -> None:
    """Fail loudly when a flag names a feature that does not exist yet.

    Only ``--ai`` is still gated here: ``--live``, ``--profile`` and
    ``--max-api-calls`` are honored by the auth, doctor and cache
    commands, and refused per-command elsewhere; ``--baseline`` applies
    an accepted-findings file wherever a report is produced.
    """
    active = _GLOBAL if options is None else options
    if active.ai:
        fail("AI assistance is not available until v0.3.0.")


@dataclass(frozen=True)
class RuntimeOptions:
    """Effective per-run rendering options after merging globals."""

    format_name: str
    out: Path | None
    strict: bool


def resolve_runtime(
    format_name: str = "json", out: Path | None = None, *, strict: bool = False
) -> RuntimeOptions:
    """Merge command-level options over the root ``--format/--out/--strict``."""
    return RuntimeOptions(
        format_name=format_name if format_name != "json" else (_GLOBAL.format_name or "json"),
        out=out or _GLOBAL.out,
        strict=strict or _GLOBAL.strict,
    )


def load_input(path: Path, module: str, input_format: str | None) -> dict[str, Any]:
    """Load a JSON input, auto-detecting ``legacy-v1`` when unambiguous."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail(f"cannot read {path}: {exc}")
    if not isinstance(data, dict):
        fail(f"{path} must contain a JSON object")
    if input_format is None:
        matches = sorted(name for name, keys in LEGACY_MARKERS.items() if keys <= data.keys())
        if matches == [module]:
            return data
        if not matches:
            fail(f"{path} matches no known legacy envelope; pass --input-format legacy-v1")
        fail(f"{path} matches {matches}; pass --input-format explicitly")
    if input_format != "legacy-v1":
        fail(f"unsupported --input-format {input_format!r} (only legacy-v1)")
    return dict(data)


def parse_model(model: type[ModelT], data: dict[str, Any]) -> ModelT:
    """Validate the envelope; exit 1 on a validation error."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        fail(str(exc).splitlines()[0] if str(exc) else "invalid input")


def fresh_context() -> RunContext:
    """Run context stamped with the current UTC time."""
    return RunContext(now=datetime.now(UTC), mode="offline")


def emit(report: Report, format_name: str, out: Path | None, *, strict: bool) -> NoReturn:
    """Render the report, write it, and exit with the resolved code."""
    try:
        render = _RENDERERS[format_name]
    except KeyError:
        fail(f"unsupported --format {format_name!r} ({FORMATS_HELP.rstrip('.')})")
    text = render(report)
    if out is None:
        typer.echo(text)
    else:
        out.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        typer.echo(f"Wrote {out}")
    raise typer.Exit(code=int(resolve(report, strict=strict)))


def apply_baseline_file(report: Report, baseline: Path | None, *, now: datetime) -> Report:
    """Apply an accepted-findings file to a report (no-op when absent).

    A missing reason (or any other validation problem) is an input error
    (exit 1) with a value-free message.
    """
    if baseline is None:
        return report
    try:
        loaded = load_baseline(baseline)
    except BaselineError as exc:
        fail(str(exc))
    return apply_baseline(report, loaded, now=now)


__all__: list[str] = [
    "FORMATS_HELP",
    "AiAfter",
    "BaselineAfter",
    "GlobalOptions",
    "LiveAfter",
    "MaxApiCallsAfter",
    "ProfileAfter",
    "RuntimeOptions",
    "apply_baseline_file",
    "check_unavailable_globals",
    "emit",
    "fail",
    "fresh_context",
    "load_input",
    "parse_model",
    "reject_future_flags",
    "reject_unsupported_live",
    "resolve_runtime",
    "set_global_options",
]
