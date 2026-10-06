"""``zohokit workflow``: simulate, lint and scenario-test rules."""

from __future__ import annotations

import hashlib
import json
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
from zohokit.modules.workflow.engine import run
from zohokit.modules.workflow.models import WorkflowInput

app = typer.Typer(help="Trace, lint and scenario-test workflow rules.")


@app.command()
def simulate(
    fixture: Annotated[Path, typer.Argument(help="JSON with rules and a record.")],
    input_format: Annotated[
        str | None, typer.Option("--input-format", help="Only legacy-v1.")
    ] = None,
    strict: Annotated[bool, typer.Option("--strict", help="Exit 2 when findings remain.")] = False,
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
    """Simulate rules against one record and report the trace."""
    reject_unsupported_live("workflow", live, profile, max_api_calls)
    reject_future_flags(ai, baseline)
    data = load_input(fixture, "workflow", input_format)
    ctx = fresh_context()
    report = run(parse_model(WorkflowInput, data), ctx=ctx)
    report = apply_baseline_file(report, baseline, now=ctx.now)
    runtime = resolve_runtime(format_name, out, strict=strict)
    emit(report, runtime.format_name, runtime.out, strict=runtime.strict)


@app.command(name="lint")
def lint_cmd(
    rules: Annotated[
        Path | None,
        typer.Option("--rules", help="JSON rules file (v2 or real-shaped envelope)."),
    ] = None,
    actions: Annotated[
        Path | None, typer.Option("--actions", help="JSON action maps for real-shaped rules.")
    ] = None,
    metadata: Annotated[
        Path | None, typer.Option("--metadata", help="JSON {module: [field api_names]}.")
    ] = None,
    module: Annotated[str, typer.Option("--module", help="Module for live reads.")] = "Deals",
    strict: Annotated[bool, typer.Option("--strict", help="Exit 2 when findings remain.")] = False,
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
        bool, typer.Option("--experimental", help="Allow unverified workflow endpoints.")
    ] = False,
) -> None:
    """Lint workflow rules for conflicts, loops, stale fields and dead rules."""
    from zohokit.core.context import RunContext
    from zohokit.core.findings import Report
    from zohokit.core.ids import canonical_json
    from zohokit.modules.workflow.analyzer import lint
    from zohokit.modules.workflow.import_real import ActionMaps, Unsupported, translate_ruleset
    from zohokit.modules.workflow.language import RulesetV2, parse_ruleset

    reject_future_flags(ai, None)
    metadata_map: dict[str, set[str]] = {}
    failures: dict[str, str] = {}
    limits: dict[str, dict[str, int]] = {}
    unsupported: list[Unsupported] = []
    if live or profile is not None or max_api_calls is not None:
        if not live:
            fail("live reads need --live --profile NAME (read-only, budget-capped)")
        if not profile:
            fail("--live requires --profile: there is no default profile")
        if not experimental:
            fail("workflow endpoints are unverified: live lint needs --experimental")
        from zohokit.connectors.zoho.errors import ConnectorError, ContractDriftError
        from zohokit.modules.workflow.live import live_lint_bundle

        try:
            payload, maps_raw, field_names, failures, limits = live_lint_bundle(
                profile, module=module, max_api_calls=max_api_calls
            )
        except ValueError as exc:
            fail(str(exc))
        except (ConnectorError, ContractDriftError) as exc:
            typer.echo(f"Connector error: {exc}", err=True)
            raise typer.Exit(code=3) from exc
        maps = ActionMaps(
            field_updates={
                key: {"field": value.get("field", ""), "value": value.get("value")}
                for key, value in maps_raw.get("field_updates", {}).items()
            },
            emails=dict(maps_raw.get("emails", {})),
            tasks=dict(maps_raw.get("tasks", {})),
            webhooks=dict(maps_raw.get("webhooks", {})),
            functions=dict(maps_raw.get("functions", {})),
        )
        ruleset, unsupported = translate_ruleset(payload, maps=maps)
        metadata_map = {module: set(field_names)}
        findings = lint(
            ruleset,
            metadata=metadata_map,
            webhook_failures=failures,
            limits=limits,
            unsupported=unsupported,
        )
        digest = hashlib.sha256(
            canonical_json({"live": profile, "module": module}).encode("utf-8")
        ).hexdigest()
        ctx = RunContext(now=datetime.now(UTC), mode="live_read")
    else:
        if rules is None:
            fail("offline lint needs --rules FILE (or --live --profile NAME)")
        try:
            data = json.loads(rules.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            fail(f"cannot read {rules}: {exc}")
        if not isinstance(data, dict):
            fail(f"{rules} must contain a JSON object")
        body = data.get("response", {}).get("body", data)
        if not isinstance(body, dict):
            fail(f"{rules} holds no rules object")
        if isinstance(body.get("workflow_rules"), list):
            maps = ActionMaps()
            if actions is not None:
                try:
                    raw = json.loads(actions.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    fail(f"cannot read {actions}: {exc}")
                actions_body = raw.get("response", {}).get("body", raw)
                maps = ActionMaps(
                    field_updates={
                        str(item.get("id", "")): {
                            "field": str((item.get("field") or {}).get("api_name", "")),
                            "value": (item.get("value") or [None])[0],
                        }
                        for item in actions_body.get("field_updates", [])
                        if isinstance(item, dict)
                    },
                    emails={},
                    tasks={},
                    webhooks={},
                    functions={},
                )
            ruleset, unsupported = translate_ruleset(body, maps=maps)
        else:
            kind, parsed = parse_ruleset(body.get("rules", []))
            if kind != "v2" or not isinstance(parsed, RulesetV2):
                fail(f"{rules} holds no v2 rules and no real-shaped workflow_rules")
            ruleset = parsed
        if metadata is not None:
            try:
                meta_raw = json.loads(metadata.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                fail(f"cannot read {metadata}: {exc}")
            metadata_map = {
                str(name): set(fields)
                for name, fields in meta_raw.items()
                if isinstance(fields, list)
            }
        findings = lint(
            ruleset,
            metadata=metadata_map or None,
            webhook_failures=failures or None,
            limits=limits or None,
            unsupported=unsupported,
        )
        digest = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
        ctx = fresh_context()
    report = Report.build(
        module="workflow",
        run_id=digest,
        started_at=ctx.now,
        finished_at=ctx.now,
        findings=findings,
        ready=not findings,
        mode=ctx.mode,
        inputs_sha256=digest,
    )
    report = apply_baseline_file(report, baseline, now=ctx.now)
    runtime = resolve_runtime(format_name, out, strict=strict)
    emit(report, runtime.format_name, runtime.out, strict=runtime.strict)


@app.command(name="test")
def test_cmd(
    directory: Annotated[Path, typer.Argument(help="Directory of scenario YAML files.")],
    strict: Annotated[bool, typer.Option("--strict", help="Exit 2 when cases fail.")] = False,
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
    """Run a directory of given/when/then rule scenarios (UC-WF-2)."""
    from zohokit.core.context import RunContext
    from zohokit.core.findings import Report
    from zohokit.core.ids import canonical_json
    from zohokit.modules.workflow.scenario import run_directory, suite_findings

    reject_unsupported_live("workflow", live, profile, max_api_calls)
    reject_future_flags(ai, baseline)
    if not directory.is_dir():
        fail(f"{directory} is not a directory")
    try:
        suites = run_directory(directory)
    except ValueError as exc:
        fail(str(exc))
    findings = [finding for suite in suites for finding in suite_findings(suite)]
    for suite in suites:
        typer.echo(
            f"{suite.file}: {sum(1 for c in suite.cases if c.passed)}/{len(suite.cases)} "
            f"cases passed; rule coverage {suite.rule_coverage:.0%} "
            f"({len(suite.covered_rules)}/{len(suite.rule_ids)}); "
            f"branch coverage {suite.branch_coverage:.0%}"
        )
    digest = hashlib.sha256(
        canonical_json(sorted(suite.file for suite in suites)).encode("utf-8")
    ).hexdigest()
    ctx: RunContext = fresh_context()
    report = Report.build(
        module="workflow",
        run_id=digest,
        started_at=ctx.now,
        finished_at=ctx.now,
        findings=findings,
        ready=not [item for item in findings if item.code == "scenario_case_failed"],
        mode=ctx.mode,
        inputs_sha256=digest,
    )
    report = apply_baseline_file(report, baseline, now=ctx.now)
    runtime = resolve_runtime(format_name, out, strict=strict)
    emit(report, runtime.format_name, runtime.out, strict=runtime.strict)


__all__: list[str] = ["app"]
