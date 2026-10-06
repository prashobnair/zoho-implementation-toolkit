"""``zohokit migration audit`` (TK-MIG-4)."""

from __future__ import annotations

import hashlib
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
from zohokit.core.findings import Severity
from zohokit.core.ids import canonical_json
from zohokit.modules import Analysis
from zohokit.modules.migration.engine import run
from zohokit.modules.migration.models import MigrationInput
from zohokit.modules.migration.report import build_report

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
    users_file: Annotated[
        Path | None,
        typer.Option("--users-file", help="Target users JSON for owner checks (offline)."),
    ] = None,
    default_region: Annotated[
        str | None,
        typer.Option("--default-region", help="Phone region for numbers without a code."),
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
    experimental: Annotated[
        bool, typer.Option("--experimental", help="Allow unverified target search (TK-MIG-F5).")
    ] = False,
) -> None:
    """Audit CSV exports against a mapping and the target field metadata."""
    from zohokit.modules.migration.preflight import ExtraChecks, SourceSpec, run_preflight

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
        if not profile:
            fail("--live requires --profile: there is no default profile")
        from zohokit.connectors.zoho.errors import ConnectorError, ContractDriftError
        from zohokit.modules.migration.live import live_metadata, live_search_fn, live_users

        modules = tuple(sorted({entity.target_module for entity in doc.entities}))
        try:
            metadata, client = live_metadata(profile, modules=modules, max_api_calls=max_api_calls)
            users, _ = live_users(profile, max_api_calls=max_api_calls)
        except ValueError as exc:
            fail(str(exc))
        except (ConnectorError, ContractDriftError) as exc:
            typer.echo(f"Connector error: {exc}", err=True)
            raise typer.Exit(code=3) from exc
        search = live_search_fn(client) if experimental else None
        extra = ExtraChecks(
            default_region=default_region,
            users=users,
            search=search,
            search_budget=max_api_calls,
        )
        ctx = RunContext(now=datetime.now(UTC), mode="live_read")
    else:
        from zohokit.modules.migration.metadata import TargetMetadata, metadata_from_dir
        from zohokit.modules.migration.owners import users_from_file

        if fields_dir is None:
            fail("--preflight needs --fields-dir DIR or --live --profile NAME for target metadata")
        try:
            metadata = metadata_from_dir(fields_dir)
        except ValueError as exc:
            fail(str(exc))
        if not metadata.modules:
            fail(f"--fields-dir {fields_dir} holds no fields_<Module>.json files")
        metadata = TargetMetadata(modules=metadata.modules)
        offline_users: dict[str, str] | None = None
        if users_file is not None:
            try:
                offline_users = users_from_file(users_file)
            except ValueError as exc:
                fail(str(exc))
        extra = ExtraChecks(default_region=default_region, users=offline_users)
        ctx = fresh_context()
    report = run_preflight(doc, sources, metadata, ctx=ctx, extra=extra)
    report = apply_baseline_file(report, baseline, now=ctx.now)
    runtime = resolve_runtime(format_name, out, strict=strict)
    emit(report, runtime.format_name, runtime.out, strict=runtime.strict)


@app.command()
def plan(
    mapping: Annotated[Path, typer.Option("--mapping", help="Field-mapping YAML (TK-MIG-F1).")],
    source: Annotated[
        Path, typer.Option("--source", help="Source dir holding <source_kind>.csv files.")
    ],
    out: Annotated[Path, typer.Option("--out", help="Directory for plan.json + plan.md.")],
    source_system: Annotated[
        str | None, typer.Option("--source-system", help="Idempotency key prefix.")
    ] = None,
    ai: AiAfter = False,
    baseline: BaselineAfter = None,
) -> None:
    """Write the signed import plan: batches, order, keys and rollback note."""
    from zohokit.modules.migration.plan import estimated_api_calls, write_plan

    reject_future_flags(ai, baseline)
    try:
        from zohokit.modules.migration.mapping import MappingConfigError, load_mapping

        doc = load_mapping(mapping)
    except MappingConfigError as exc:
        fail(str(exc))
    if not source.is_dir():
        fail(f"--source {source} is not a directory")
    from zohokit.modules.migration.preflight import SOURCE_FORMATS, SourceSpec, open_entity

    source_format = doc.source if doc.source in SOURCE_FORMATS else "generic"
    counts: dict[str, int] = {}
    for entity in doc.entities:
        candidate = source / f"{entity.source_kind}.csv"
        if not candidate.is_file():
            fail(f"--source {source} misses {entity.source_kind}.csv for entity {entity.name}")
        try:
            stream = open_entity(source_format, SourceSpec(str(candidate)), entity.source_kind)
        except ValueError as exc:
            fail(str(exc))
        try:
            counts[entity.name] = sum(
                1 for _, row, issue in stream.rows() if issue is None and row is not None
            )
        finally:
            stream.close()
    json_path, md_path, built = write_plan(doc, counts, out, source_system=source_system)
    typer.echo(f"Wrote {json_path}")
    typer.echo(f"Wrote {md_path}")
    typer.echo(f"Plan SHA-256: {built.canonical_hash()}")
    typer.echo(f"Estimated API calls: {estimated_api_calls(built)}")


@app.command()
def reconcile(
    mapping: Annotated[Path, typer.Option("--mapping", help="Field-mapping YAML (TK-MIG-F1).")],
    source: Annotated[
        Path, typer.Option("--source", help="Source dir holding <source_kind>.csv files.")
    ],
    target: Annotated[
        Path, typer.Option("--target", help="Target dir holding <TargetModule>.csv dumps.")
    ],
    workbook: Annotated[Path, typer.Option("--workbook", help="XLSX workbook output path.")],
    seed: Annotated[int, typer.Option("--seed", help="Deterministic sample seed.")] = 42,
    strict: Annotated[bool, typer.Option("--strict", help="Exit 2 when not ready.")] = False,
    format_name: Annotated[
        str, typer.Option("--format", help="json|table|markdown|html|sarif|junit|xlsx.")
    ] = "json",
    out: Annotated[Path | None, typer.Option("--out", help="Write the report to a file.")] = None,
    ai: AiAfter = False,
    baseline: BaselineAfter = None,
) -> None:
    """Compare sources against target dumps; write the reconcile workbook."""
    from zohokit.modules.migration.reconcile import recap_findings
    from zohokit.modules.migration.reconcile import reconcile as run_reconcile

    reject_future_flags(ai, baseline)
    try:
        from zohokit.modules.migration.mapping import MappingConfigError, load_mapping

        doc = load_mapping(mapping)
    except MappingConfigError as exc:
        fail(str(exc))
    if not source.is_dir():
        fail(f"--source {source} is not a directory")
    if not target.is_dir():
        fail(f"--target {target} is not a directory")
    source_paths: dict[str, str] = {}
    for entity in doc.entities:
        candidate = source / f"{entity.source_kind}.csv"
        if not candidate.is_file():
            fail(f"--source {source} misses {entity.source_kind}.csv for entity {entity.name}")
        source_paths[entity.name] = str(candidate)
    recaps, book = run_reconcile(doc, source_paths, str(target), seed=seed)
    workbook.write_bytes(book)
    typer.echo(f"Wrote {workbook}")
    ctx = fresh_context()
    findings = recap_findings(recaps)
    ready = not any(item.severity == Severity.ERROR for item in findings)
    digest = hashlib.sha256(
        canonical_json({"mapping": doc.model_dump(mode="json"), "seed": seed}).encode()
    ).hexdigest()
    report = build_report(
        Analysis(findings=tuple(findings), legacy={}, ready=ready), ctx=ctx, inputs_sha256=digest
    )
    report = apply_baseline_file(report, baseline, now=ctx.now)
    runtime = resolve_runtime(format_name, out, strict=strict)
    emit(report, runtime.format_name, runtime.out, strict=runtime.strict)


__all__: list[str] = ["app"]
