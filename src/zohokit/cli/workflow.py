"""``zohokit workflow``: simulate, lint and scenario-test rules."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from zohokit.cli.common import (
    AI_DISABLED_NOTE,
    AiAfter,
    AiAllowPiiAfter,
    AiMaxTokensAfter,
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
    resolve_ai_runtime,
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
        Path | None,
        typer.Option("--metadata", help="JSON {module: \\[field api_names]}."),
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
    from zohokit.modules.workflow.draft import explain_lint_loops
    from zohokit.modules.workflow.import_real import ActionMaps, Unsupported, translate_ruleset
    from zohokit.modules.workflow.language import RulesetV2, parse_ruleset

    ai_runtime = resolve_ai_runtime(ai=ai, live=live)
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
    findings = explain_lint_loops(
        findings,
        provider=ai_runtime.provider,
        allow_pii=ai_runtime.allow_pii,
        budget_tokens=ai_runtime.max_tokens,
    )
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
    from zohokit.modules.workflow.scenario import coverage_block, run_directory, suite_findings

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
        coverage=coverage_block(suites),
    )
    report = apply_baseline_file(report, baseline, now=ctx.now)
    runtime = resolve_runtime(format_name, out, strict=strict)
    emit(report, runtime.format_name, runtime.out, strict=runtime.strict)


def _load_draft_fields(metadata: Path | None, module: str) -> dict[str, str] | None:
    """Field name → type map for the drafter, or None for the built-ins."""
    if metadata is None:
        return None
    try:
        raw = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail(f"cannot read {metadata}: {exc}")
    if not isinstance(raw, dict):
        fail(f"{metadata} must be a JSON object ({{field: type}} or {{module: [names]}})")
    scoped = raw.get(module)
    if isinstance(scoped, list):
        if not scoped or not all(isinstance(name, str) for name in scoped):
            fail(f"{metadata} module {module!r} must list field api_names")
        return {str(name): "string" for name in scoped}
    if all(isinstance(value, str) for value in raw.values()):
        return {str(name): value for name, value in raw.items()}
    fail(f"{metadata} must be {{field: type}} or {{module: [field api_names]}}")


def _load_allow_targets(path: Path | None) -> tuple[str, ...]:
    """Pre-approved action targets, or () when no allowlist is given."""
    if path is None:
        return ()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail(f"cannot read {path}: {exc}")
    if not isinstance(raw, list) or not all(isinstance(entry, str) for entry in raw):
        fail(f"{path} must be a JSON list of strings")
    return tuple(raw)


def _load_draft_record(path: Path | None) -> dict[str, Any]:
    """Record to simulate the draft against (default: a synthetic deal)."""
    from zohokit.modules.workflow.draft import DEFAULT_DRAFT_RECORD

    if path is None:
        return dict(DEFAULT_DRAFT_RECORD)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail(f"cannot read {path}: {exc}")
    if not isinstance(raw, dict):
        fail(f"{path} must contain a JSON object")
    return raw


@app.command(name="draft")
def draft_cmd(
    description: Annotated[
        str, typer.Option("--description", help="Natural-language rule description.")
    ],
    metadata: Annotated[
        Path | None,
        typer.Option("--metadata", help="JSON {field: type} or {module: [field api_names]}."),
    ] = None,
    module: Annotated[str, typer.Option("--module", help="Module the rule belongs to.")] = "Deals",
    record: Annotated[
        Path | None,
        typer.Option("--record", help="JSON record to simulate the draft against."),
    ] = None,
    allow_targets: Annotated[
        Path | None,
        typer.Option("--allow-targets", help="JSON list of pre-approved action targets."),
    ] = None,
    format_name: Annotated[
        str, typer.Option("--format", help="json|table|markdown|html.")
    ] = "json",
    out: Annotated[Path | None, typer.Option("--out", help="Write the draft to a file.")] = None,
    ai: AiAfter = False,
    ai_allow_pii: AiAllowPiiAfter = False,
    ai_max_tokens: AiMaxTokensAfter = None,
    live: LiveAfter = False,
    profile: ProfileAfter = None,
    baseline: BaselineAfter = None,
    max_api_calls: MaxApiCallsAfter = None,
) -> None:
    """Draft one rule from a description and simulate it (UC-WF-4, AI-WF-1).

    The draft simulates immediately against --record (default: a small
    synthetic Marigold deal) and prints the full trace. Draft only, not
    deployed: nothing is written anywhere except --out.
    """
    from zohokit.modules.workflow.draft import (
        build_draft_output,
        render_draft_html,
        render_draft_markdown,
        render_draft_table,
        suggest_draft,
    )

    reject_unsupported_live("workflow", live, profile, max_api_calls)
    if baseline is not None:
        fail("draft takes no --baseline (it proposes, it suppresses none)")
    if not description.strip():
        fail("--description must not be empty")
    runtime = resolve_ai_runtime(ai=ai, allow_pii=ai_allow_pii, max_tokens=ai_max_tokens, live=live)
    if runtime.provider is None and not ai:
        typer.echo(AI_DISABLED_NOTE, err=True)
    fields = _load_draft_fields(metadata, module)
    allowed = _load_allow_targets(allow_targets)
    subject: dict[str, Any] = _load_draft_record(record)
    result = suggest_draft(
        description,
        fields,
        provider=runtime.provider,
        allow_pii=runtime.allow_pii,
        budget_tokens=runtime.max_tokens,
        allow_targets=allowed,
    )
    output = build_draft_output(result, subject)
    if format_name == "json":
        text = output.model_dump_json(indent=2) + "\n"
    elif format_name == "table":
        text = render_draft_table(output)
    elif format_name == "markdown":
        text = render_draft_markdown(output)
    elif format_name == "html":
        text = render_draft_html(output)
    else:
        fail(f"unsupported --format {format_name!r} (json|table|markdown|html)")
    if out is None:
        typer.echo(text)
    else:
        out.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        typer.echo(f"Wrote {out}")


__all__: list[str] = ["app"]
