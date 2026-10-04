"""Release v2 tests: manifest, inference, risk, order, rollback, comment."""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from zohokit.cli import app
from zohokit.core.context import RunContext
from zohokit.core.ids import finding_id
from zohokit.core.plan import verify_bundle
from zohokit.modules.release.comment import COMMENT_MARKER, MAX_COMMENT_CHARS, render_pr_comment
from zohokit.modules.release.diff import diff_manifests
from zohokit.modules.release.engine_v2 import analyze_drift, analyze_manifest, run_manifest
from zohokit.modules.release.infer import infer_edges
from zohokit.modules.release.manifest import (
    EXPERIMENTAL_KINDS,
    coerce_component,
    coerce_manifest,
    is_v2_item,
    manifest_fingerprint,
)
from zohokit.modules.release.risk import assess, release_risk
from zohokit.modules.release.rollback import is_data_losing

ROOT = Path(__file__).resolve().parent.parent.parent.parent
FIXTURES = ROOT / "fixtures" / "release"
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
runner = CliRunner()


def _ctx() -> RunContext:
    return RunContext(now=NOW, mode="offline")


def _pair() -> tuple[list[object], list[object]]:
    before = json.loads((FIXTURES / "before.json").read_text())["components"]
    after = json.loads((FIXTURES / "after.json").read_text())["components"]
    return before, after


def test_legacy_v1_items_coerce_with_defaults() -> None:
    component = coerce_component({"kind": "field", "name": "Deal.External_Ref"})
    assert component.attributes == {}
    assert component.module == ""
    assert component.component_id() == "field:Deal.External_Ref"
    assert not is_v2_item({"kind": "field", "name": "x"})
    assert is_v2_item({"kind": "field", "name": "x", "attributes": {}})
    assert is_v2_item({"kind": "blueprint", "name": "x"})


def test_unknown_kind_and_duplicates_rejected() -> None:
    with pytest.raises(ValueError, match="unknown component kind"):
        coerce_component({"kind": "portal", "name": "x"})
    with pytest.raises(ValueError, match="duplicate component"):
        coerce_manifest([{"kind": "field", "name": "x"}, {"kind": "field", "name": "x"}])


def test_fingerprint_ignores_order_and_env() -> None:
    before, _ = _pair()
    first = coerce_manifest(before, source_env="prod")
    assert manifest_fingerprint(first) == manifest_fingerprint(
        coerce_manifest(list(reversed(before)), source_env="sandbox")
    )
    for ordering in itertools.islice(itertools.permutations(first.components), 0, 20):
        assert manifest_fingerprint(
            coerce_manifest([item.model_dump(mode="json") for item in ordering], source_env="prod")
        ) == manifest_fingerprint(first)


def test_attribute_diff_before_after() -> None:
    before, _ = _pair()
    changed = [dict(item) for item in before]
    for item in changed:
        if item["name"] == "Deals.Main":
            item["attributes"] = {"enabled": True}
    mutated = coerce_manifest(changed)
    flipped = coerce_manifest(
        [
            {**item, "attributes": {"enabled": False}} if item["name"] == "Deals.Main" else item
            for item in (entry.model_dump(mode="json") for entry in mutated.components)
        ]
    )
    diff = diff_manifests(list(mutated.components), list(flipped.components))
    assert diff.changed == ("layout:Deals.Main",)
    (entry,) = diff.changes[0].attributes
    assert entry.attribute == "enabled"
    assert entry.describe() == "enabled: true → false"


def test_change_findings_carry_attribute_before_after() -> None:
    """TK-REL-4: each change finding shows exactly what changed, before → after."""
    before, after = _pair()
    analysis = analyze_manifest(
        list(coerce_manifest(before).components), list(coerce_manifest(after).components)
    )
    by_key = {(finding.code, finding.entity_id): finding for finding in analysis.findings}
    type_finding = by_key[("field_type_change", "field:Deals.Close_Date")]
    assert type_finding.evidence["changes"] == [
        {"attribute": "data_type", "before": "date", "after": "datetime"}
    ]
    assert type_finding.message == (
        'field_type_change: field:Deals.Close_Date changed type (data_type: "date" → "datetime")'
    )
    behavior = by_key[("behavior_regression_review", "workflow:Deals.AutoAssign")]
    assert behavior.evidence["changes"] == [
        {"attribute": "enabled", "before": True, "after": False},
        {
            "attribute": "target_fields",
            "before": ["Deals.Amount"],
            "after": ["Deals.New_Score"],
        },
    ]
    assert behavior.message == (
        "behavior_regression_review: workflow:Deals.AutoAssign was changed"
        " (enabled: true → false;"
        ' target_fields: ["Deals.Amount"] → ["Deals.New_Score"])'
    )
    removed = by_key[("removal_review", "field:Deals.External_Ref")]
    assert removed.evidence["changes"] == []
    assert removed.message == "removal_review: field:Deals.External_Ref was removed"
    # IDs stay stable: the new evidence never feeds the discriminator.
    assert type_finding.id == finding_id(
        "release",
        "field_type_change",
        "manifest",
        "field:Deals.Close_Date",
        "field:Deals.Close_Date\x00data_type",
    )
    assert behavior.id == finding_id(
        "release",
        "behavior_regression_review",
        "manifest",
        "workflow:Deals.AutoAssign",
        "workflow:Deals.AutoAssign",
    )
    drifted = analyze_drift(
        list(coerce_manifest(before).components), list(coerce_manifest(after).components)
    )
    drift = next(
        finding
        for finding in drifted.findings
        if finding.code == "unapproved_drift" and finding.entity_id == "field:Deals.Close_Date"
    )
    assert drift.evidence["changes"] == [
        {"attribute": "data_type", "before": "date", "after": "datetime"}
    ]
    assert 'data_type: "date" → "datetime"' in drift.message


def test_pr_comment_and_html_render_attribute_changes() -> None:
    """TK-REL-4: the PR comment details and the HTML report show before/after."""
    from zohokit.reports import render_html

    before, after = _pair()
    report, analysis = run_manifest(
        list(coerce_manifest(before).components),
        list(coerce_manifest(after).components),
        ctx=_ctx(),
    )
    comment = render_pr_comment(report, analysis.diff, analysis.deploy, analysis.release_risk)
    assert '- `data_type: "date" → "datetime"`' in comment
    assert "- `enabled: true → false`" in comment
    field_block = next(
        block
        for block in comment.split("<details>")
        if "field_type_change" in block and "field:Deals.Close_Date" in block
    )
    assert 'data_type: "date" → "datetime"' in field_block
    html = render_html(report)
    assert "data_type" in html
    assert "datetime" in html
    assert "enabled" in html


def test_inference_edge_types() -> None:
    _, after = _pair()
    manifest = coerce_manifest(after)
    edges = infer_edges(list(manifest.components))
    heuristic = {(edge.source, edge.target) for edge in edges if edge.confidence == "heuristic"}
    assert ("layout:Deals.Main", "field:Deals.Amount") in heuristic
    assert ("workflow:Deals.AutoAssign", "field:Deals.Stage") in heuristic
    assert ("workflow:Deals.AutoAssign", "field:Deals.New_Score") in heuristic
    assert ("function:Post_Deal", "field:Deals.Amount") in heuristic
    assert ("custom_button:Deals.Convert", "field:Deals.Stage") in heuristic
    declared = [edge for edge in edges if edge.confidence == "declared"]
    assert [(edge.source, edge.target) for edge in declared] == [
        ("workflow:Deals.AutoAssign", "function:Missing_Func")
    ]
    assert all(edge.confidence in ("declared", "heuristic") for edge in edges)


def test_risk_table_per_class() -> None:
    before, after = _pair()
    analysis = analyze_manifest(
        list(coerce_manifest(before).components), list(coerce_manifest(after).components)
    )
    levels = {risk.component_id: risk.level for risk in analysis.risks}
    assert levels == {
        "custom_button:Deals.Convert": "low",
        "field:Deals.Close_Date": "high",
        "field:Deals.External_Ref": "high",
        "field:Deals.New_Score": "medium",
        "layout:Deals.Main": "low",
        "layout_rule:Deals.ShowRef": "low",
        "picklist_value:Deals.Stage.Negotiation": "high",
        "workflow:Deals.AutoAssign": "high",
    }
    assert analysis.release_risk == "high"
    assert release_risk(list(analysis.risks)) == "high"
    picklist = next(
        risk
        for risk in analysis.risks
        if risk.component_id == "picklist_value:Deals.Stage.Negotiation"
    )
    assert picklist.reasons == ("removal", "picklist value removed while records use it")


def test_finding_codes_and_stable_ids() -> None:
    before, after = _pair()
    report, analysis = run_manifest(
        list(coerce_manifest(before).components),
        list(coerce_manifest(after).components),
        ctx=_ctx(),
    )
    assert report.ready is False
    codes = sorted((finding.code, finding.entity_id) for finding in analysis.findings)
    assert ("behavior_regression_review", "workflow:Deals.AutoAssign") in codes
    assert ("experimental_kind", "blueprint:Deals.Blueprint") in codes
    assert ("field_type_change", "field:Deals.Close_Date") in codes
    assert ("heuristic_dependency", "layout:Deals.Main") in codes
    assert ("irreversible_change", "field:Deals.External_Ref") in codes
    assert ("missing_dependency", "workflow:Deals.AutoAssign") in codes
    assert ("picklist_value_in_use", "picklist_value:Deals.Stage.Negotiation") in codes
    assert ("removal_review", "field:Deals.External_Ref") in codes
    assert ("removal_review", "picklist_value:Deals.Stage.Negotiation") in codes
    assert len(analysis.findings) == 17
    rerun = analyze_manifest(
        list(coerce_manifest(before).components), list(coerce_manifest(after).components)
    )
    assert [item.id for item in rerun.findings] == [item.id for item in analysis.findings]
    assert is_data_losing(next(c for c in analysis.diff.changes if c.change == "removed"))


def test_golden_deploy_order() -> None:
    before, after = _pair()
    analysis = analyze_manifest(
        list(coerce_manifest(before).components), list(coerce_manifest(after).components)
    )
    expected = json.loads((FIXTURES / "expected_deploy_order.json").read_text())
    assert list(analysis.deploy.deploy) == expected["deploy"]
    assert list(analysis.deploy.removals) == expected["removals"]
    assert analysis.deploy.cycles == ()
    assert {risk.component_id: risk.level for risk in analysis.risks} == expected["risks"]


def test_dependency_cycle_error() -> None:
    payload = json.loads((FIXTURES / "cycle.json").read_text())
    analysis = analyze_manifest(
        list(coerce_manifest(payload["before"]).components),
        list(coerce_manifest(payload["after"]).components),
    )
    assert analysis.deploy.deploy == ()
    assert analysis.release_risk in ("low", "medium", "high")
    cycles = [finding for finding in analysis.findings if finding.code == "dependency_cycle"]
    assert len(cycles) == 1
    assert cycles[0].severity.value == "error"
    assert analysis.ready is False


def test_rollback_plan_inverses_and_signature(tmp_path: Path) -> None:
    before, after = _pair()
    analysis = analyze_manifest(
        list(coerce_manifest(before).components), list(coerce_manifest(after).components)
    )
    by_path = {call.path: call for call in analysis.rollback.calls}
    assert by_path["manifest/field:Deals.External_Ref"].method == "CREATE"
    assert by_path["manifest/field:Deals.New_Score"].method == "DELETE"
    assert by_path["manifest/field:Deals.Close_Date"].method == "UPDATE"
    assert len(analysis.rollback.calls) == len(analysis.diff.changes) == 8
    from zohokit.core.plan import write_bundle

    json_path, _ = write_bundle(analysis.rollback, tmp_path, note="review only")
    assert json_path.is_file()
    assert verify_bundle(tmp_path).canonical_hash() == analysis.rollback.canonical_hash()
    assert EXPERIMENTAL_KINDS == frozenset({"blueprint", "client_script", "profile_permission"})


def test_pr_comment_shape_and_truncation() -> None:
    before, after = _pair()
    report, analysis = run_manifest(
        list(coerce_manifest(before).components),
        list(coerce_manifest(after).components),
        ctx=_ctx(),
    )
    comment = render_pr_comment(report, analysis.diff, analysis.deploy, analysis.release_risk)
    assert comment.startswith(COMMENT_MARKER)
    assert "# Release gate: NOT READY" in comment
    assert "Risk **high**" in comment
    assert "<details>" in comment
    assert "6. `workflow:Deals.AutoAssign`" in comment
    assert "1. `picklist_value:Deals.Stage.Negotiation`" in comment
    assert 'data_type: "date" → "datetime"' in comment
    assert len(comment) <= MAX_COMMENT_CHARS
    huge = render_pr_comment(report, analysis.diff, analysis.deploy, analysis.release_risk)
    assert huge == comment


def test_pr_comment_truncates_with_note() -> None:
    before, after = _pair()
    report, analysis = run_manifest(
        list(coerce_manifest(before).components),
        list(coerce_manifest(after).components),
        ctx=_ctx(),
    )
    from zohokit.modules.release import comment as comment_module

    original = comment_module.MAX_COMMENT_CHARS
    comment_module.MAX_COMMENT_CHARS = 1200
    try:
        text = render_pr_comment(report, analysis.diff, analysis.deploy, analysis.release_risk)
    finally:
        comment_module.MAX_COMMENT_CHARS = original
    assert len(text) <= 1200
    assert "Truncated:" in text
    assert "findings omitted" in text
    assert COMMENT_MARKER in text
    assert "## Deploy order" in text


def test_drift_flags_unapproved_changes() -> None:
    before, after = _pair()
    analysis = analyze_drift(
        list(coerce_manifest(before).components), list(coerce_manifest(after).components)
    )
    drifted = [finding for finding in analysis.findings if finding.code == "unapproved_drift"]
    assert len(drifted) == 8
    assert all(finding.severity.value == "error" for finding in drifted)
    assert analysis.ready is False


def test_cli_v2_outputs(tmp_path: Path) -> None:
    before, after = _pair()
    envelope = tmp_path / "envelope.json"
    envelope.write_text(
        json.dumps({"before": before, "after": after}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    comment_out = tmp_path / "comment.md"
    order_out = tmp_path / "order.json"
    plan_dir = tmp_path / "rollback"
    result = runner.invoke(
        app,
        [
            "release",
            "diff",
            str(envelope),
            "--pr-comment-out",
            str(comment_out),
            "--deploy-order-out",
            str(order_out),
            "--rollback-plan-out",
            str(plan_dir),
        ],
    )
    assert result.exit_code == 0
    comment = comment_out.read_text(encoding="utf-8")
    assert comment.startswith(COMMENT_MARKER)
    assert "Risk **high**" in comment
    order = json.loads(order_out.read_text(encoding="utf-8"))
    expected = json.loads((FIXTURES / "expected_deploy_order.json").read_text())
    assert order == expected
    assert verify_bundle(plan_dir).calls[0].method in ("CREATE", "DELETE", "UPDATE")


def test_cli_v1_rejects_v2_outputs(tmp_path: Path) -> None:
    fixture = ROOT / "tests" / "golden" / "legacy" / "release" / "inputs" / "examples.json"
    result = runner.invoke(
        app,
        ["release", "diff", str(fixture), "--deploy-order-out", str(tmp_path / "o.json")],
    )
    assert result.exit_code == 1
    assert "v2 outputs need manifest v2" in result.output


def test_assess_unit_levels() -> None:
    from zohokit.modules.release.diff import ComponentChange

    assert assess(ComponentChange("a", "layout", "L", "changed")).level == "low"
    assert assess(ComponentChange("b", "field", "F", "added")).level == "medium"
    assert assess(ComponentChange("c", "workflow", "W", "added")).level == "high"
    assert assess(ComponentChange("d", "field", "F", "removed")).level == "high"


def test_cli_before_after_sides() -> None:
    result = runner.invoke(
        app,
        [
            "release",
            "diff",
            "--before",
            str(FIXTURES / "before.json"),
            "--after",
            str(FIXTURES / "after.json"),
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ready"] is False
    assert payload["summary"]["error"] >= 1
    both = runner.invoke(app, ["release", "diff", "--before", str(FIXTURES / "before.json")])
    assert both.exit_code == 1
    assert "--before and --after must be passed together" in both.output


def test_demo_fixture_pair_is_clean() -> None:
    """The --before/--after path on an unchanged pair is READY.

    Reads only before.json for both sides: the demo after.json is
    intentionally dirtied by the demo PR, so no unit test may depend on
    it staying clean (the demo workflow covers the live pair instead).
    """
    result = runner.invoke(
        app,
        [
            "release",
            "diff",
            "--before",
            str(FIXTURES / "demo" / "before.json"),
            "--after",
            str(FIXTURES / "demo" / "before.json"),
        ],
    )
    assert result.exit_code == 0
    assert json.loads(result.output)["ready"] is True
