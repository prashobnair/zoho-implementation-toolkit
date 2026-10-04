"""``zohokit migration audit`` (TK-MIG-4)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from zohokit.cli.common import (
    AiAfter,
    BaselineAfter,
    LiveAfter,
    MaxApiCallsAfter,
    ProfileAfter,
    apply_baseline_file,
    emit,
    fail,
    fresh_context,
    load_input,
    parse_model,
    reject_future_flags,
    reject_unsupported_live,
    resolve_runtime,
)
from zohokit.core.context import RunContext
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
        str, typer.Option("--format", help="json|table|markdown|html|sarif|junit|xlsx.")
    ] = "json",
    out: Annotated[Path | None, typer.Option("--out", help="Write the report to a file.")] = None,
    live: LiveAfter = False,
    profile: ProfileAfter = None,
    ai: AiAfter = False,
    baseline: BaselineAfter = None,
    max_api_calls: MaxApiCallsAfter = None,
) -> None:
    """Audit a source export and report what would break on import."""
    reject_unsupported_live("migration", live, profile, max_api_calls)
    reject_future_flags(ai, baseline)
    data = load_input(fixture, "migration", input_format)
    ctx = fresh_context()
    report = run(parse_model(MigrationInput, data), ctx=ctx)
    report = apply_baseline_file(report, baseline, now=ctx.now)
    runtime = resolve_runtime(format_name, out, strict=strict)
    emit(report, runtime.format_name, runtime.out, strict=runtime.strict)


@app.command()
def preflight(
    mapping: Annotated[Path, typer.Option("--mapping", help="Field-mapping YAML (TK-MIG-F1).")],
    source: Annotated[
        Path, typer.Option("--source", help="Source dir holding <source_kind>.csv files.")
    ],
    fields_dir: Annotated[
        Path | None,
        typer.Option("--fields-dir", help="Dir of fields_<Module>.json metadata (offline)."),
    ] = None,
    strict: Annotated[bool, typer.Option("--strict", help="Exit 2 when not ready.")] = False,
    format_name: Annotated[
        str, typer.Option("--format", help="json|table|markdown|html|sarif|junit|xlsx.")
    ] = "json",
    out: Annotated[Path | None, typer.Option("--out", help="Write the report to a file.")] = None,
    live: LiveAfter = False,
    profile: ProfileAfter = None,
    ai: AiAfter = False,
    baseline: BaselineAfter = None,
    max_api_calls: MaxApiCallsAfter = None,
) -> None:
    """Audit CSV exports against a mapping and the target field metadata."""
    from zohokit.modules.migration.preflight import SourceSpec, run_preflight

    reject_future_flags(ai, baseline)
    if live or profile is not None or max_api_calls is not None:
        if not live:
            fail("live reads need --live --profile NAME (read-only, budget-capped)")
        if not profile:
            fail("--live requires --profile: there is no default profile")
    try:
        from zohokit.modules.migration.mapping import MappingConfigError, load_mapping

        doc = load_mapping(mapping)
    except MappingConfigError as exc:
        fail(str(exc))
    if not source.is_dir():
        fail(f"--source {source} is not a directory")
    sources: dict[str, SourceSpec] = {}
    for entity in doc.entities:
        candidate = source / f"{entity.source_kind}.csv"
        if not candidate.is_file():
            fail(f"--source {source} misses {entity.source_kind}.csv for entity {entity.name}")
        sources[entity.name] = SourceSpec(path=str(candidate), kind=entity.source_kind)
    if live:
        assert profile is not None
        from zohokit.connectors.zoho.errors import ConnectorError, ContractDriftError
        from zohokit.modules.migration.live import live_metadata

        modules = tuple(sorted({entity.target_module for entity in doc.entities}))
        try:
            metadata, _ = live_metadata(profile, modules=modules, max_api_calls=max_api_calls)
        except ValueError as exc:
            fail(str(exc))
        except (ConnectorError, ContractDriftError) as exc:
            typer.echo(f"Connector error: {exc}", err=True)
            raise typer.Exit(code=3) from exc
        ctx = RunContext(now=datetime.now(UTC), mode="live_read")
    else:
        from zohokit.modules.migration.metadata import TargetMetadata, metadata_from_dir

        if fields_dir is None:
            fail("--preflight needs --fields-dir DIR or --live --profile NAME for target metadata")
        try:
            metadata = metadata_from_dir(fields_dir)
        except ValueError as exc:
            fail(str(exc))
        if not metadata.modules:
            fail(f"--fields-dir {fields_dir} holds no fields_<Module>.json files")
        metadata = TargetMetadata(modules=metadata.modules)
        ctx = fresh_context()
    report = run_preflight(doc, sources, metadata, ctx=ctx)
    report = apply_baseline_file(report, baseline, now=ctx.now)
    runtime = resolve_runtime(format_name, out, strict=strict)
    emit(report, runtime.format_name, runtime.out, strict=runtime.strict)


__all__: list[str] = ["app"]
