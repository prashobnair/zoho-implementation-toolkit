"""Workflow live-reader replay over synthetic v8 cassettes (TK-WF-F4 live path).

The CRM v8 Workflow Rules / Actions endpoints are `unverified` (see
``docs/API_CONTRACTS.md``): live calls need ``--experimental``. These
tests replay synthetic cassettes shaped like the real v8 envelopes
(``{"workflow_rules": [...], "info": {...}}`` and the same list pattern
for actions, confirmed against the official docs via webfetch) through
the shared GET-only client — no network, no Zoho calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from zohokit.connectors.zoho.client import ZohoClient
from zohokit.connectors.zoho.errors import ConnectorError
from zohokit.modules.workflow.live import (
    read_automation_tasks,
    read_email_notifications,
    read_field_updates,
    read_webhook_failures,
    read_webhooks,
    read_workflow_configurations,
    read_workflow_rule,
    read_workflow_rules,
)

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parent.parent.parent
CASSETTES = ROOT / "tests" / "contract" / "cassettes"


def _body(name: str) -> dict[str, object]:
    envelope = json.loads((CASSETTES / name).read_text(encoding="utf-8"))
    body = envelope["response"]["body"]
    assert isinstance(body, dict)
    return body


def _client() -> ZohoClient:
    bodies = {
        "/crm/v8/settings/automation/workflow_rules": _body("crm_workflow_rules.json"),
        "/crm/v8/settings/automation/workflow_rules/5550000000011000002": _body(
            "crm_workflow_rule_single.json"
        ),
        "/crm/v8/settings/automation/field_updates": _body("crm_field_updates.json"),
        "/crm/v8/settings/automation/email_notifications": _body("crm_email_notifications.json"),
        "/crm/v8/settings/automation/tasks": _body("crm_automation_tasks.json"),
        "/crm/v8/settings/automation/webhooks": _body("crm_webhooks.json"),
        "/crm/v8/settings/automation/webhook_failures": _body("crm_webhook_failures.json"),
        "/crm/v8/workflow_configurations": _body("crm_workflow_configurations.json"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = bodies.get(request.url.path)
        if body is None:
            return httpx.Response(404, json={"code": "INVALID_URL_PATTERN"})
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    return ZohoClient("https://www.zohoapis.in", transport=transport)


def test_workflow_cassettes_use_v8_list_envelopes() -> None:
    assert sorted(_body("crm_workflow_rules.json")) == ["info", "workflow_rules"]
    single = _body("crm_workflow_rule_single.json")
    assert sorted(single) == ["workflow_rules"]
    assert sorted(_body("crm_webhook_failures.json")) == ["info", "webhook_failures"]
    assert sorted(_body("crm_workflow_configurations.json")) == ["workflow_configurations"]


def test_unverified_workflow_endpoints_need_experimental() -> None:
    client = _client()
    with pytest.raises(ConnectorError, match="unverified"):
        client.get(
            "/crm/v8/settings/automation/workflow_rules",
            endpoint="/crm/v8/settings/automation/workflow_rules",
        )


def test_workflow_readers_replay_cassettes() -> None:
    client = _client()
    rules = read_workflow_rules(client, module="Deals")
    assert [rule["id"] for rule in rules.workflow_rules] == [
        "5550000000011000001",
        "5550000000011000002",
    ]
    single = read_workflow_rule(client, "5550000000011000002")
    assert single["name"] == "Follow up on negotiation"
    assert single["conditions"][0]["scheduled_actions"][0]["execute_after"] == {
        "period": "days",
        "unit": 2,
    }
    updates = read_field_updates(client)
    assert updates.field_updates[0]["field"]["api_name"] == "Stage"
    assert read_email_notifications(client).email_notifications[0]["name"] == "Notify owner"
    assert read_automation_tasks(client).tasks[0]["name"] == "Follow up task"
    webhooks = read_webhooks(client)
    assert webhooks.webhooks[0]["url"] == "https://example.invalid/hooks/billing"
    failures = read_webhook_failures(client)
    assert failures.webhook_failures[0]["failure_reason"] == "timeout"
    configs = read_workflow_configurations(client, module="Deals")
    triggers = {item["api_name"] for item in configs.workflow_configurations["triggers"]}
    assert {"create", "field_update"} <= triggers
