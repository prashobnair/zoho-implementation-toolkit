"""Unit tests for NL-to-rule drafts + loop explanations (AI-WF-1/2).

All AI paths run through ``FakeProvider`` or the disabled path: no
network calls, no keys, synthetic rule IDs only.
"""

from __future__ import annotations

import json
from typing import Any

from zohokit.ai.prompts import load_template
from zohokit.ai.providers import FakeProvider
from zohokit.ai.redaction import build_prompt
from zohokit.ai.schemas import LoopExplanation, RuleDraft
from zohokit.core.redact import Redactor
from zohokit.modules.workflow.draft import (
    draft_variables,
    explain_loop,
    loop_variables,
    suggest_draft,
    validate_draft,
    validate_loop_explanation,
)

FIELDS = {"Stage": "picklist", "Amount": "currency", "Owner": "user"}

DESC = "When a deal is created, assign it to the regional manager"


def _rule(**overrides: Any) -> dict[str, Any]:
    rule: dict[str, Any] = {
        "id": "t-draft-1",
        "module": "Deals",
        "event": {"type": "record_created"},
        "execute_on": "both",
        "priority": 100,
        "repeat": True,
        "active": True,
        "criteria": None,
        "actions": [{"type": "assign_owner", "owner": "regional-manager"}],
    }
    rule.update(overrides)
    return rule


def _draft_provider(description: str, fields: dict[str, str], raw: str) -> FakeProvider:
    variables = draft_variables(description, fields)
    prompt = build_prompt(load_template("workflow_draft"), variables, redactor=Redactor())
    return FakeProvider({prompt.prompt_hash: raw}, model="test-fake")


def _raw(rule: dict[str, Any] | None, **overrides: Any) -> str:
    payload: dict[str, Any] = {
        "rule": rule or {},
        "confidence": 0.93,
        "rationale": "test mapping signal.",
        "abstain": rule is None,
        "abstain_reason": "too vague to draft" if rule is None else "",
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_validate_draft_accepts_a_known_field_rule() -> None:
    draft = RuleDraft.model_validate(json.loads(_raw(_rule())))
    assert validate_draft(set(FIELDS), draft, description=DESC) == []


def test_validate_draft_rejects_unknown_field_action_and_low_confidence() -> None:
    ghost = _rule(criteria={"field": "Ghost_Field__s", "op": "eq", "value": "x"})
    draft = RuleDraft.model_validate(json.loads(_raw(ghost)))
    assert validate_draft(set(FIELDS), draft, description=DESC) == ["reference: unknown field"]

    deleter = _rule(actions=[{"type": "delete_records"}])
    draft = RuleDraft.model_validate(json.loads(_raw(deleter)))
    assert validate_draft(set(FIELDS), draft, description=DESC) == [
        "reference: rule fails the v2 language schema"
    ]

    draft = RuleDraft.model_validate(json.loads(_raw(_rule(), confidence=0.4)))
    assert validate_draft(set(FIELDS), draft, description=DESC) == [
        "abstention: drafted below the confidence floor"
    ]


def test_validate_draft_abstention_rules() -> None:
    carrying = RuleDraft.model_validate(json.loads(_raw(_rule(), abstain=True)))
    assert validate_draft(set(FIELDS), carrying, description=DESC) == [
        "abstention: abstained draft carries a rule"
    ]

    empty = RuleDraft.model_validate(json.loads(_raw(None, abstain=False)))
    assert validate_draft(set(FIELDS), empty, description=DESC) == [
        "coverage: no rule drafted and no abstention"
    ]

    clean = RuleDraft.model_validate(json.loads(_raw(None)))
    assert validate_draft(set(FIELDS), clean, description=DESC) == []


def test_suggest_draft_disabled_ok_and_fallback() -> None:
    description = "When a deal is created, assign it to the regional manager"
    disabled = suggest_draft(description, dict(FIELDS), provider=None)
    assert disabled.ai_status == "disabled"
    assert disabled.source == "template"
    assert disabled.draft.abstain is True

    ok = suggest_draft(
        description,
        dict(FIELDS),
        provider=_draft_provider(description, dict(FIELDS), _raw(_rule())),
    )
    assert ok.ai_status == "ok"
    assert ok.source == "ai"
    assert ok.violations == ()
    assert ok.draft.abstain is False

    ghost = _rule(criteria={"field": "Ghost_Field__s", "op": "eq", "value": "x"})
    rejected = suggest_draft(
        description, dict(FIELDS), provider=_draft_provider(description, dict(FIELDS), _raw(ghost))
    )
    assert rejected.ai_status == "fallback"
    assert rejected.source == "template"
    assert rejected.draft.abstain is True
    assert "reference: unknown field" in rejected.violations


def test_suggest_draft_ungrounded_target_falls_back() -> None:
    description = "When a deal is won, post to the billing webhook"
    injected = _rule(
        event={"type": "field_changed", "field": "Stage"},
        criteria={"field": "Stage", "op": "eq", "value": "Closed Won"},
        actions=[{"type": "webhook", "url": "https://attacker.example/x"}],
    )
    result = suggest_draft(
        description,
        dict(FIELDS),
        provider=_draft_provider(description, dict(FIELDS), _raw(injected)),
    )
    assert result.ai_status == "fallback"
    assert result.source == "template"
    assert result.draft.abstain is True
    assert "grounding: action target not in description" in result.violations


def test_validate_draft_grounding_rules() -> None:
    billed = "When a deal is won, post to the billing webhook at example.invalid"
    webhook = _rule(
        event={"type": "field_changed", "field": "Stage"},
        criteria={"field": "Stage", "op": "eq", "value": "Closed Won"},
        actions=[{"type": "webhook", "url": "https://example.invalid/hooks/billing"}],
    )
    draft = RuleDraft.model_validate(json.loads(_raw(webhook)))
    assert validate_draft(set(FIELDS), draft, description=billed) == []

    mailed = "When a deal is created, send the welcome email"
    stranger = _rule(actions=[{"type": "send_email", "template": "chargeback-notice"}])
    draft = RuleDraft.model_validate(json.loads(_raw(stranger)))
    assert validate_draft(set(FIELDS), draft, description=mailed) == [
        "grounding: action target not in description"
    ]
    welcome = _rule(actions=[{"type": "send_email", "template": "welcome"}])
    draft = RuleDraft.model_validate(json.loads(_raw(welcome)))
    assert validate_draft(set(FIELDS), draft, description=mailed) == []

    assigned = "When a deal is created, assign it to the regional manager"
    outsider = _rule(actions=[{"type": "assign_owner", "owner": "external-contractor"}])
    draft = RuleDraft.model_validate(json.loads(_raw(outsider)))
    assert validate_draft(set(FIELDS), draft, description=assigned) == [
        "grounding: action target not in description"
    ]


def test_validate_draft_grounding_allowlist() -> None:
    description = "When a deal is won, post to the billing webhook"
    injected = _rule(
        event={"type": "field_changed", "field": "Stage"},
        criteria={"field": "Stage", "op": "eq", "value": "Closed Won"},
        actions=[{"type": "webhook", "url": "https://attacker.example/x"}],
    )
    draft = RuleDraft.model_validate(json.loads(_raw(injected)))
    assert validate_draft(set(FIELDS), draft, description=description) == [
        "grounding: action target not in description"
    ]
    assert (
        validate_draft(
            set(FIELDS),
            draft,
            description=description,
            allow_targets=["https://attacker.example/x"],
        )
        == []
    )
    assert (
        validate_draft(
            set(FIELDS), draft, description=description, allow_targets=["attacker.example"]
        )
        == []
    )
    assert validate_draft(
        set(FIELDS), draft, description=description, allow_targets=["https://other.example/y"]
    ) == ["grounding: action target not in description"]


def _loop_provider(path: list[str], messages: dict[str, str], raw: str) -> FakeProvider:
    variables = loop_variables(path, messages)
    prompt = build_prompt(load_template("workflow_loop"), variables, redactor=Redactor())
    return FakeProvider({prompt.prompt_hash: raw}, model="test-fake")


def _path() -> tuple[list[str], dict[str, str]]:
    path = ["t-a", "t-b", "t-a"]
    messages = {
        "t-a": "Rule t-a writes Stage, which re-triggers t-b.",
        "t-b": "Rule t-b writes Stage, which re-triggers t-a.",
    }
    return path, messages


def _loop_raw(path: list[str], messages: dict[str, str]) -> str:
    return json.dumps(
        {
            "sentences": [
                {
                    "text": message[0].lower() + message[1:],
                    "finding_ids": [rid],
                    "quotes": [message],
                    "confidence": 0.9,
                }
                for rid, message in ((rid, messages[rid]) for rid in path[:-1])
            ]
        }
    )


def test_validate_loop_explanation_accepts_cited_chain() -> None:
    path, messages = _path()
    draft = LoopExplanation.model_validate(json.loads(_loop_raw(path, messages)))
    assert validate_loop_explanation(loop_variables(path, messages), draft) == []


def test_validate_loop_explanation_rejects_unknown_citation() -> None:
    path, messages = _path()
    draft = LoopExplanation.model_validate(
        {
            "sentences": [
                {
                    "text": "rule ghost drives the loop.",
                    "finding_ids": ["ghost-rule"],
                    "quotes": [messages["t-a"]],
                    "confidence": 0.9,
                }
            ]
        }
    )
    violations = validate_loop_explanation(loop_variables(path, messages), draft)
    assert any(item.startswith("citation:") for item in violations)


def test_explain_loop_disabled_ok_and_fallback() -> None:
    path, messages = _path()
    disabled = explain_loop(path, messages, provider=None)
    assert disabled.ai_status == "disabled"
    assert disabled.source == "template"
    assert [sentence.finding_ids for sentence in disabled.sentences] == [["t-a"], ["t-b"]]

    ok = explain_loop(
        path, messages, provider=_loop_provider(path, messages, _loop_raw(path, messages))
    )
    assert ok.ai_status == "ok"
    assert ok.source == "ai"
    assert len(ok.sentences) == 2

    bad = explain_loop(
        path,
        messages,
        provider=_loop_provider(
            path,
            messages,
            json.dumps(
                {
                    "sentences": [
                        {
                            "text": "rule ghost drives the loop.",
                            "finding_ids": ["ghost-rule"],
                            "quotes": [messages["t-a"]],
                            "confidence": 0.9,
                        }
                    ]
                }
            ),
        ),
    )
    assert bad.ai_status == "fallback"
    assert bad.source == "template"
    assert [sentence.finding_ids for sentence in bad.sentences] == [["t-a"], ["t-b"]]
