"""``zohokit release``: manifest diffs, snapshots and drift (TK-REL-1..10)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any, Literal

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
from zohokit.connectors.zoho.errors import ConnectorError, ContractDriftError
from zohokit.core.context import RunContext
from zohokit.core.findings import Report
from zohokit.core.ids import canonical_json
from zohokit.core.plan import Plan, write_bundle
from zohokit.modules.release.comment import render_pr_comment
from zohokit.modules.release.engine import run
from zohokit.modules.release.engine_v2 import analyze_drift, run_manifest
from zohokit.modules.release.manifest import (
    Component,
    coerce_component,
    coerce_manifest,
    is_v2_item,
)
from zohokit.modules.release.models import ReleaseInput
from zohokit.modules.release.rollback import plan_note
from zohokit.modules.release.snapshot import (
    DEFAULT_SNAPSHOT_MODULES,
    read_snapshot,
    write_snapshot,
)

app = typer.Typer(help="Diff sandbox vs production config manifests.")

ReportMode = Literal["offline", "live_read"]


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        fail(f"cannot read {path}: {exc.strerror or exc}")
    except ValueError:
        fail(f"{path} is not valid JSON")


def _load_envelope(
    fixture: Path | None,
    before_file: Path | None,
    after_file: Path | None,
    input_format: str | None,
) -> dict[str, Any]:
    """Load the before/after envelope from one file or two side files."""
    if before_file is not None or after_file is not None:
        if fixture is not None:
            fail("pass either FIXTURE or --before/--after, not both")
        if before_file is None or after_file is None:
            fail("--before and --after must be passed together")
        if input_format is not None:
            fail("--input-format only applies to the single-file envelope")
        return {
            "before": _load_side(before_file),
            "after": _load_side(after_file),
        }
    if fixture is None:
        fail("missing FIXTURE (or pass --before/--after)")
    return load_input(fixture, "release", input_format)


def _load_side(path: Path) -> list[Any]:
    """Load one manifest side: a component list or a Manifest envelope."""
    payload = _read_json(path)
    items = payload.get("components", payload) if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        fail(f"{path} must hold a component list")
    return items


def _is_v2_envelope(data: dict[str, Any]) -> bool:
    items = list(data.get("before", [])) + list(data.get("after", []))
    return any(is_v2_item(item) for item in items)


def _parse_modules(modules: str) -> tuple[str, ...]:
    module_list = tuple(part.strip() for part in modules.split(",") if part.strip())
    if not module_list:
        fail("--modules must name at least one CRM module")
    return module_list


@app.command()
def diff(
    fixture: Annotated[
        Path | None, typer.Argument(help="JSON with before/after manifests.")
    ] = None,
    before_file: Annotated[
        Path | None, typer.Option("--before", help="Before manifest file.")
    ] = None,
    after_file: Annotated[Path | None, typer.Option("--after", help="After manifest file.")] = None,
    input_format: Annotated[
        str | None, typer.Option("--input-format", help="Only legacy-v1.")
    ] = None,
    strict: Annotated[bool, typer.Option("--strict", help="Exit 2 when not ready.")] = False,
    format_name: Annotated[
        str, typer.Option("--format", help="json|table|markdown|html|sarif|junit.")
    ] = "json",
    out: Annotated[Path | None, typer.Option("--out", help="Write the report to a file.")] = None,
    live: LiveAfter = False,
    profile: ProfileAfter = None,
    ai: AiAfter = False,
    baseline: BaselineAfter = None,
    max_api_calls: MaxApiCallsAfter = None,
    plan_out: Annotated[
        Path | None, typer.Option("--plan-out", help="Write a signed plan bundle here.")
    ] = None,
    pr_comment_out: Annotated[
        Path | None, typer.Option("--pr-comment-out", help="Write the PR comment Markdown here.")
    ] = None,
    rollback_plan_out: Annotated[
        Path | None, typer.Option("--rollback-plan-out", help="Write the rollback plan here.")
    ] = None,
    deploy_order_out: Annotated[
        Path | None, typer.Option("--deploy-order-out", help="Write the deploy order JSON here.")
    ] = None,
) -> None:
    """Diff two manifests and report blocking changes."""
    reject_unsupported_live("release", live, profile, max_api_calls)
    reject_future_flags(ai, baseline)
    data = _load_envelope(fixture, before_file, after_file, input_format)
    ctx = fresh_context()
    if _is_v2_envelope(data):
        _diff_v2(
            data,
            ctx=ctx,
            baseline=baseline,
            plan_out=plan_out,
            pr_comment_out=pr_comment_out,
            rollback_plan_out=rollback_plan_out,
            deploy_order_out=deploy_order_out,
            format_name=format_name,
            out=out,
            strict=strict,
        )
    if pr_comment_out is not None or rollback_plan_out is not None or deploy_order_out is not None:
        fail("v2 outputs need manifest v2 items (attributes or v2 kinds)")
    report = run(parse_model(ReleaseInput, data), ctx=ctx)
    report = apply_baseline_file(report, baseline, now=ctx.now)
    if plan_out is not None:
        json_path, _ = write_bundle(
            Plan(),
            plan_out,
            note=(
                "Offline diff proposes no writes to Zoho. "
                "A future live promotion would list its calls here for review."
            ),
        )
        typer.echo(f"Wrote {json_path}")
    runtime = resolve_runtime(format_name, out, strict=strict)
    emit(report, runtime.format_name, runtime.out, strict=runtime.strict)


def _diff_v2(
    data: dict[str, Any],
    *,
    ctx: RunContext,
    baseline: Path | None,
    plan_out: Path | None,
    pr_comment_out: Path | None,
    rollback_plan_out: Path | None,
    deploy_order_out: Path | None,
    format_name: str,
    out: Path | None,
    strict: bool,
) -> None:
    """Manifest v2 path: diff plus deploy order, rollback plan and comment."""
    before = coerce_manifest(data["before"])
    after = coerce_manifest(data["after"])
    report, analysis = run_manifest(list(before.components), list(after.components), ctx=ctx)
    report = apply_baseline_file(report, baseline, now=ctx.now)
    if pr_comment_out is not None:
        comment = render_pr_comment(report, analysis.diff, analysis.deploy, analysis.release_risk)
        pr_comment_out.write_text(comment, encoding="utf-8")
        typer.echo(f"Wrote {pr_comment_out}")
    if rollback_plan_out is not None:
        json_path, _ = write_bundle(
            analysis.rollback, rollback_plan_out, note=plan_note(len(analysis.diff.changes))
        )
        typer.echo(f"Wrote {json_path}")
    if deploy_order_out is not None:
        payload = {
            "deploy": list(analysis.deploy.deploy),
            "removals": list(analysis.deploy.removals),
            "release_risk": analysis.release_risk,
            "risks": {risk.component_id: risk.level for risk in analysis.risks},
        }
        deploy_order_out.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        typer.echo(f"Wrote {deploy_order_out}")
    if plan_out is not None:
        json_path, _ = write_bundle(
            analysis.rollback, plan_out, note=plan_note(len(analysis.diff.changes))
        )
        typer.echo(f"Wrote {json_path}")
    runtime = resolve_runtime(format_name, out, strict=strict)
    emit(report, runtime.format_name, runtime.out, strict=runtime.strict)


@app.command()
def snapshot(
    profile: Annotated[str, typer.Option("--profile", help="Named auth profile.")] = "",
    out: Annotated[Path, typer.Option("--out", help="Write one file per kind here.")] = Path(
        "config/zoho"
    ),
    modules: Annotated[
        str, typer.Option("--modules", help="Comma-separated CRM modules.")
    ] = ",".join(DEFAULT_SNAPSHOT_MODULES),
    import_dir: Annotated[
        Path | None,
        typer.Option("--import-dir", help="User-exported JSON for unverified kinds."),
    ] = None,
    strict: Annotated[bool, typer.Option("--strict", help="Exit 2 when not ready.")] = False,
    format_name: Annotated[
        str, typer.Option("--format", help="json|table|markdown|html|sarif|junit.")
    ] = "json",
    live: LiveAfter = False,
    ai: AiAfter = False,
    baseline: BaselineAfter = None,
    max_api_calls: MaxApiCallsAfter = None,
    experimental: Annotated[
        bool, typer.Option("--experimental", help="Allow unverified manifest surface.")
    ] = False,
) -> None:
    """Snapshot an org to config/zoho (normalized, sorted, redacted)."""
    from zohokit.modules.release.live import live_snapshot

    reject_future_flags(ai, baseline)
    if not live:
        fail("snapshot reads from Zoho: pass --live --profile NAME (read-only, budget-capped)")
    if not profile:
        fail("--live requires --profile: there is no default profile")
    if not experimental:
        fail("snapshot is new surface: pass --experimental (reads stay GET-only)")
    module_list = _parse_modules(modules)
    extra = _load_import_dir(import_dir, source_env=profile) if import_dir is not None else None
    try:
        manifest, _ = live_snapshot(
            profile, modules=module_list, extra=extra, max_api_calls=max_api_calls
        )
    except ValueError as exc:
        fail(str(exc))
    except (ConnectorError, ContractDriftError) as exc:
        typer.echo(f"Connector error: {exc}", err=True)
        raise typer.Exit(code=3) from exc
    for path in write_snapshot(manifest, out):
        typer.echo(f"Wrote {path}")
    ctx = fresh_context()
    report, _ = run_manifest([], list(manifest.components), ctx=ctx)
    report = apply_baseline_file(report, baseline, now=ctx.now)
    runtime = resolve_runtime(format_name, None, strict=strict)
    emit(report, runtime.format_name, runtime.out, strict=runtime.strict)


@app.command()
def drift(
    approved: Annotated[Path, typer.Option("--approved", help="Approved snapshot dir.")] = Path(
        "config/zoho"
    ),
    after: Annotated[
        Path | None, typer.Option("--after", help="Compare against this manifest file.")
    ] = None,
    profile: Annotated[str | None, typer.Option("--profile", help="Named auth profile.")] = None,
    modules: Annotated[
        str, typer.Option("--modules", help="Comma-separated CRM modules.")
    ] = ",".join(DEFAULT_SNAPSHOT_MODULES),
    strict: Annotated[bool, typer.Option("--strict", help="Exit 2 when not ready.")] = False,
    format_name: Annotated[
        str, typer.Option("--format", help="json|table|markdown|html|sarif|junit.")
    ] = "json",
    out: Annotated[Path | None, typer.Option("--out", help="Write the report to a file.")] = None,
    live: LiveAfter = False,
    ai: AiAfter = False,
    baseline: BaselineAfter = None,
    max_api_calls: MaxApiCallsAfter = None,
    experimental: Annotated[
        bool, typer.Option("--experimental", help="Allow unverified manifest surface.")
    ] = False,
) -> None:
    """Diff approved manifests against live (or a file); flag unapproved drift."""
    from zohokit.modules.release.live import live_snapshot

    reject_future_flags(ai, baseline)
    try:
        approved_manifest = read_snapshot(approved)
    except ValueError as exc:
        fail(str(exc))
    if after is not None:
        if live or profile is not None:
            fail("pass either --after or --live --profile, not both")
        payload = _read_json(after)
        items = payload.get("components", payload) if isinstance(payload, dict) else payload
        try:
            live_manifest = coerce_manifest(items, source_env="after")
        except ValueError as exc:
            fail(f"invalid --after manifest: {exc}")
    else:
        if not live:
            fail("drift reads from Zoho: pass --live --profile NAME or --after FILE")
        if profile is None:
            fail("--live requires --profile: there is no default profile")
        if not experimental:
            fail("drift is new surface: pass --experimental (reads stay GET-only)")
        module_list = _parse_modules(modules)
        try:
            live_manifest, _ = live_snapshot(
                profile, modules=module_list, max_api_calls=max_api_calls
            )
        except ValueError as exc:
            fail(str(exc))
        except (ConnectorError, ContractDriftError) as exc:
            typer.echo(f"Connector error: {exc}", err=True)
            raise typer.Exit(code=3) from exc
    ctx = fresh_context()
    analysis = analyze_drift(list(approved_manifest.components), list(live_manifest.components))
    inputs_sha = hashlib.sha256(
        canonical_json([item.model_dump(mode="json") for item in live_manifest.components]).encode(
            "utf-8"
        )
    ).hexdigest()
    report_mode: ReportMode = "live_read" if live else "offline"
    report = Report.build(
        module="release",
        run_id=inputs_sha,
        started_at=ctx.now,
        finished_at=ctx.now,
        findings=list(analysis.findings),
        ready=analysis.ready,
        mode=report_mode,
        inputs_sha256=inputs_sha,
    )
    report = apply_baseline_file(report, baseline, now=ctx.now)
    runtime = resolve_runtime(format_name, out, strict=strict)
    emit(report, runtime.format_name, runtime.out, strict=runtime.strict)


def _load_import_dir(import_dir: Path, *, source_env: str) -> list[Component]:
    """Validate user-exported JSON files into components (v1 or v2 items)."""
    components: list[Component] = []
    if not import_dir.is_dir():
        fail(f"--import-dir {import_dir} is not a directory")
    for path in sorted(import_dir.glob("*.json")):
        payload = _read_json(path)
        items = payload.get("components", payload) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            fail(f"{path} must hold a component list")
        for item in items:
            try:
                component = coerce_component(item)
            except ValueError as exc:
                fail(f"{path} holds an invalid component: {exc}")
            if not component.source_env:
                component = component.model_copy(update={"source_env": source_env})
            components.append(component)
    return components


__all__: list[str] = ["app"]
