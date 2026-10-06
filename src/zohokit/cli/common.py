"""Shared CLI plumbing: input loading, rendering, exit codes (TK-MIG-4)."""

from __future__ import annotations

import contextlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, NoReturn, TypeAlias, TypeVar

import typer
from pydantic import BaseModel, ValidationError

from zohokit.ai.models import AiConfig
from zohokit.ai.providers import LLMProvider, build_provider
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
from zohokit.reports.xlsx import render_xlsx

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
FORMATS_HELP = "json|table|markdown|html|sarif|junit|xlsx."


def ensure_utf8_stdio() -> None:
    """Force UTF-8 on stdout/stderr so ``→`` never crashes a cp1252 pipe.

    Windows consoles and redirected pipes default to cp1252 unless
    ``PYTHONIOENCODING``/``PYTHONUTF8`` say otherwise; the release v2
    attribute diffs intentionally contain ``→`` (U+2192), which cp1252
    cannot encode. Reconfiguring with ``errors="replace"`` keeps every
    other platform unchanged (already UTF-8) while guaranteeing the CLI
    never raises ``UnicodeEncodeError`` on print. No-op when the streams
    lack ``reconfigure`` (captured test streams, pipes without the API).
    """

    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with contextlib.suppress(Exception):
                reconfigure(encoding="utf-8", errors="replace")


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
    silently ignoring them. ``ai`` opts into AI suggestions: with no
    provider configured the tool says "AI disabled" and runs its
    deterministic path (STD-AI4). ``ai_allow_pii`` skips prompt
    redaction for synthetic-only local runs and is refused with
    ``--live`` (STD-AI8). ``ai_max_tokens`` caps estimated prompt
    tokens before the deterministic fallback runs (STD-AI9).
    ``baseline`` applies an accepted-findings file. ``format_name``,
    ``out`` and ``strict`` act as defaults when the command does not
    set them.
    """

    live: bool = False
    profile: str | None = None
    format_name: str | None = None
    out: Path | None = None
    strict: bool = False
    ai: bool = False
    ai_allow_pii: bool = False
    ai_max_tokens: int | None = None
    baseline: Path | None = None
    max_api_calls: int | None = None


_GLOBAL = GlobalOptions()


# After-subcommand spellings of the root flags (TK-X-1).
#
# Click only accepts root options *before* the subcommand, so every leaf
# command re-declares these flags with identical help text.
# ``--ai-allow-pii``/``--ai-max-tokens`` are re-declared only by commands
# that run AI features; ``--baseline`` applies an accepted-findings file.
# ``--live``/``--profile``/``--max-api-calls`` are honored by the auth,
# doctor and cache commands; every other command refuses them loudly
# (see :func:`reject_unsupported_live`) until its live path is wired.
LiveAfter: TypeAlias = Annotated[
    bool, typer.Option("--live", help="Read from Zoho via a named profile.")
]
ProfileAfter: TypeAlias = Annotated[
    str | None,
    typer.Option("--profile", help="Named auth profile (see `zohokit auth login`)."),
]
AiAfter: TypeAlias = Annotated[
    bool,
    typer.Option("--ai", help="AI suggestions (says 'AI disabled' when unconfigured)."),
]
AiAllowPiiAfter: TypeAlias = Annotated[
    bool,
    typer.Option(
        "--ai-allow-pii",
        help="Send unredacted values to the AI provider (synthetic data only).",
    ),
]
AiMaxTokensAfter: TypeAlias = Annotated[
    int | None,
    typer.Option("--ai-max-tokens", help="Cap estimated AI prompt tokens."),
]
BaselineAfter: TypeAlias = Annotated[
    Path | None,
    typer.Option("--baseline", help="Accepted-findings file (.zohokit-baseline.json)."),
]
MaxApiCallsAfter: TypeAlias = Annotated[
    int | None,
    typer.Option("--max-api-calls", help="API call budget per run (default 200)."),
]


#: Note printed when --ai is given but no provider is configured (STD-AI4).
AI_DISABLED_NOTE = "AI disabled: no provider configured; the deterministic path runs."


@dataclass(frozen=True)
class AiRuntime:
    """Resolved AI setup for one command invocation (STD-AI4/8/9).

    ``use_ai`` is False (with ``provider`` None) when ``--ai`` was not
    given or no provider is configured; commands then run their
    deterministic path. ``allow_pii``/``max_tokens`` merge the command
    flags over the root defaults.
    """

    use_ai: bool
    provider: LLMProvider | None
    allow_pii: bool
    max_tokens: int | None


def resolve_ai_runtime(
    *,
    ai: bool = False,
    allow_pii: bool = False,
    max_tokens: int | None = None,
    live: bool = False,
) -> AiRuntime:
    """Merge AI flags and resolve the provider, or fall back loudly.

    ``--ai-allow-pii`` with ``--live`` fails (STD-AI8). With ``--ai``
    but no provider configured, notes "AI disabled" and returns an
    inactive runtime so the deterministic path runs (STD-AI4).
    """
    use_allow_pii = allow_pii or _GLOBAL.ai_allow_pii
    if use_allow_pii and (live or _GLOBAL.live):
        fail("--ai-allow-pii is refused with --live: live prompts stay redacted.")
    budget = max_tokens if max_tokens is not None else _GLOBAL.ai_max_tokens
    use_ai = ai or _GLOBAL.ai
    if not use_ai:
        return AiRuntime(False, None, use_allow_pii, budget)
    provider = build_provider(AiConfig.from_env())
    if provider is None:
        typer.echo(AI_DISABLED_NOTE, err=True)
        return AiRuntime(False, None, use_allow_pii, budget)
    return AiRuntime(True, provider, use_allow_pii, budget)


def reject_future_flags(
    ai: bool = False,
    baseline: Path | None = None,
) -> None:
    """Accept the after-subcommand flags every command declares.

    ``--ai`` is opt-in (STD-AI4): with no provider configured the tool
    notes "AI disabled" on stderr and runs its deterministic path. AI
    features themselves consume the flag; commands without one simply
    run deterministically. ``--baseline`` is accepted by every command
    that produces a report; the parameter stays so existing call sites
    keep working while each command wires it to
    :func:`apply_baseline_file`.
    """
    active = ai or _GLOBAL.ai
    if active and build_provider(AiConfig.from_env()) is None:
        typer.echo(AI_DISABLED_NOTE, err=True)
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
    """Fail loudly when a flag combination is not allowed.

    ``--ai-allow-pii`` is refused with ``--live`` (STD-AI8): prompts
    built from live reads must always pass the redactor first.
    ``--live``, ``--profile`` and ``--max-api-calls`` are honored by the
    auth, doctor and cache commands, and refused per-command elsewhere;
    ``--baseline`` applies an accepted-findings file wherever a report
    is produced; ``--ai`` opts in per command (STD-AI4).
    """
    active = _GLOBAL if options is None else options
    if active.ai_allow_pii and active.live:
        fail("--ai-allow-pii is refused with --live: live prompts stay redacted.")


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
    if format_name == "xlsx":
        if out is None:
            fail("xlsx output needs --out (workbooks cannot print to stdout)")
        out.write_bytes(render_xlsx(report))
        typer.echo(f"Wrote {out}")
        raise typer.Exit(code=int(resolve(report, strict=strict)))
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
    "AI_DISABLED_NOTE",
    "FORMATS_HELP",
    "AiAfter",
    "AiAllowPiiAfter",
    "AiMaxTokensAfter",
    "AiRuntime",
    "BaselineAfter",
    "GlobalOptions",
    "LiveAfter",
    "MaxApiCallsAfter",
    "ProfileAfter",
    "RuntimeOptions",
    "apply_baseline_file",
    "check_unavailable_globals",
    "emit",
    "ensure_utf8_stdio",
    "fail",
    "fresh_context",
    "load_input",
    "parse_model",
    "reject_future_flags",
    "reject_unsupported_live",
    "resolve_ai_runtime",
    "resolve_runtime",
    "set_global_options",
]
