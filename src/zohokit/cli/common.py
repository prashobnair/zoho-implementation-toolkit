"""Shared CLI plumbing: input loading, rendering, exit codes (TK-MIG-4)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn, TypeVar

import typer
from pydantic import BaseModel, ValidationError

from zohokit.cli.exitcodes import resolve
from zohokit.core.context import RunContext
from zohokit.core.findings import Report
from zohokit.reports import render_html, render_json, render_markdown, render_table

ModelT = TypeVar("ModelT", bound=BaseModel)

LEGACY_MARKERS: dict[str, set[str]] = {
    "migration": {"organizations", "people", "deals", "activities"},
    "release": {"before", "after"},
    "workflow": {"rules", "record"},
    "forms": {"source_fields", "target_fields", "cases"},
}

_RENDERERS = {
    "json": render_json,
    "table": render_table,
    "markdown": render_markdown,
    "html": render_html,
}


def fail(message: str) -> NoReturn:
    """Exit 1 with a usage/input error (STD §3.5)."""
    typer.echo(f"Input error: {message}", err=True)
    raise typer.Exit(code=1)


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
        fail(f"unsupported --format {format_name!r} (json|table|markdown|html)")
    text = render(report)
    if out is None:
        typer.echo(text)
    else:
        out.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        typer.echo(f"Wrote {out}")
    raise typer.Exit(code=int(resolve(report, strict=strict)))


__all__: list[str] = ["emit", "fail", "fresh_context", "load_input", "parse_model"]
