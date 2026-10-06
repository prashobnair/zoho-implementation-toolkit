"""Read-only CRM workflow + actions readers (TK-WF-F4 live path).

All endpoints below are **unverified** against the live Developer
Edition org (see ``docs/API_CONTRACTS.md``): envelope shapes follow the
official Zoho CRM v8 docs
(``{"workflow_rules": [...], "info": {...}}`` for lists,
``{"workflow_rules": [...]}`` for single reads, and the same list
pattern for ``field_updates`` / ``email_notifications`` / ``tasks`` /
``webhooks`` / ``webhook_failures``), so every reader requires
``experimental=True`` (``--experimental`` on the CLI) and warns per
STD-C2. Tests replay synthetic cassettes shaped like those envelopes;
no call here can write (GET-only client).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from pydantic import Field

from zohokit.connectors.zoho.auth import TokenManager
from zohokit.connectors.zoho.budget import DEFAULT_MAX_API_CALLS, CallBudget
from zohokit.connectors.zoho.client import ZohoClient
from zohokit.connectors.zoho.dc import DC_TABLE
from zohokit.connectors.zoho.errors import ContractDriftError
from zohokit.connectors.zoho.models import (
    FieldsResponse,
    ZohoResponse,
    unwrap_fields,
    validate_response,
)
from zohokit.connectors.zoho.profiles import load_profile
from zohokit.connectors.zoho.readers import (
    authenticated_client,
    raise_for_zoho_error,
    read_model,
)
from zohokit.modules.workflow.import_real import ACTION_MAP

#: Workflow + actions endpoints (all unverified; experimental only).
WORKFLOW_RULES_PATH = "/crm/v8/settings/automation/workflow_rules"
FIELD_UPDATES_PATH = "/crm/v8/settings/automation/field_updates"
EMAIL_NOTIFICATIONS_PATH = "/crm/v8/settings/automation/email_notifications"
AUTOMATION_TASKS_PATH = "/crm/v8/settings/automation/tasks"
WEBHOOKS_PATH = "/crm/v8/settings/automation/webhooks"
WEBHOOK_FAILURES_PATH = "/crm/v8/settings/automation/webhook_failures"
WORKFLOW_CONFIGURATIONS_PATH = "/crm/v8/workflow_configurations"


class WorkflowRulesPage(ZohoResponse):
    """List reply: ``{"workflow_rules": [...], "info": {...}}`` (v8)."""

    workflow_rules: list[dict[str, Any]] = Field(min_length=1)
    info: dict[str, Any] | None = None


class FieldUpdatesPage(ZohoResponse):
    """List reply: ``{"field_updates": [...], "info": {...}}`` (v8)."""

    field_updates: list[dict[str, Any]] = Field(min_length=1)
    info: dict[str, Any] | None = None


class EmailNotificationsPage(ZohoResponse):
    """List reply: ``{"email_notifications": [...], "info": {...}}`` (v8)."""

    email_notifications: list[dict[str, Any]] = Field(min_length=1)
    info: dict[str, Any] | None = None


class AutomationTasksPage(ZohoResponse):
    """List reply: ``{"tasks": [...], "info": {...}}`` (v8)."""

    tasks: list[dict[str, Any]] = Field(min_length=1)
    info: dict[str, Any] | None = None


class WebhooksPage(ZohoResponse):
    """List reply: ``{"webhooks": [...], "info": {...}}`` (v8)."""

    webhooks: list[dict[str, Any]] = Field(min_length=1)
    info: dict[str, Any] | None = None


class WebhookFailuresPage(ZohoResponse):
    """Failures reply: ``{"webhook_failures": [...], "info": {...}}`` (v8)."""

    webhook_failures: list[dict[str, Any]] = Field(min_length=1)
    info: dict[str, Any] | None = None


class WorkflowConfigurations(ZohoResponse):
    """Config reply: ``{"workflow_configurations": {...}}`` (v8)."""

    workflow_configurations: dict[str, Any]


def _get_json(client: ZohoClient, path: str, *, params: dict[str, Any] | None) -> Any:
    endpoint = path
    response = client.get(path, params=params, endpoint=endpoint, experimental=True)
    raise_for_zoho_error(response, endpoint=endpoint)
    if response.status_code == 204:
        raise ContractDriftError(endpoint, "empty response (HTTP 204)")
    try:
        return response.json()
    except ValueError as exc:
        from zohokit.connectors.zoho.errors import ConnectorError

        raise ConnectorError(f"{endpoint} returned non-JSON") from exc


def read_workflow_rules(
    client: ZohoClient, *, module: str | None = None, page: int = 1, per_page: int = 200
) -> WorkflowRulesPage:
    """GET the workflow-rules list (unverified; experimental only)."""
    params: dict[str, Any] = {"page": page, "per_page": per_page}
    if module:
        params["module"] = module
    payload = _get_json(client, WORKFLOW_RULES_PATH, params=params)
    return validate_response(WorkflowRulesPage, endpoint=WORKFLOW_RULES_PATH, payload=payload)


def read_workflow_rule(client: ZohoClient, rule_id: str) -> dict[str, Any]:
    """GET one workflow rule with conditions + actions (experimental only)."""
    if not rule_id:
        raise ContractDriftError(WORKFLOW_RULES_PATH, "rule id: missing")
    payload = _get_json(client, f"{WORKFLOW_RULES_PATH}/{rule_id}", params=None)
    page = validate_response(WorkflowRulesPage, endpoint=WORKFLOW_RULES_PATH, payload=payload)
    if not page.workflow_rules:
        raise ContractDriftError(WORKFLOW_RULES_PATH, "workflow_rules: empty list")
    return page.workflow_rules[0]


def read_field_updates(client: ZohoClient) -> FieldUpdatesPage:
    """GET the field-update actions list (experimental only)."""
    payload = _get_json(client, FIELD_UPDATES_PATH, params=None)
    return validate_response(FieldUpdatesPage, endpoint=FIELD_UPDATES_PATH, payload=payload)


def read_email_notifications(client: ZohoClient) -> EmailNotificationsPage:
    """GET the email-notification actions list (experimental only)."""
    payload = _get_json(client, EMAIL_NOTIFICATIONS_PATH, params=None)
    return validate_response(
        EmailNotificationsPage, endpoint=EMAIL_NOTIFICATIONS_PATH, payload=payload
    )


def read_automation_tasks(client: ZohoClient) -> AutomationTasksPage:
    """GET the automation-tasks list (experimental only)."""
    payload = _get_json(client, AUTOMATION_TASKS_PATH, params=None)
    return validate_response(AutomationTasksPage, endpoint=AUTOMATION_TASKS_PATH, payload=payload)


def read_webhooks(client: ZohoClient) -> WebhooksPage:
    """GET the webhooks list (experimental only)."""
    payload = _get_json(client, WEBHOOKS_PATH, params=None)
    return validate_response(WebhooksPage, endpoint=WEBHOOKS_PATH, payload=payload)


def read_webhook_failures(client: ZohoClient) -> WebhookFailuresPage:
    """GET recent webhook failures (experimental only)."""
    payload = _get_json(client, WEBHOOK_FAILURES_PATH, params=None)
    return validate_response(WebhookFailuresPage, endpoint=WEBHOOK_FAILURES_PATH, payload=payload)


def read_workflow_configurations(client: ZohoClient, *, module: str) -> WorkflowConfigurations:
    """GET trigger/action metadata for *module* (experimental only)."""
    if not module:
        raise ContractDriftError(WORKFLOW_CONFIGURATIONS_PATH, "module: missing")
    payload = _get_json(client, WORKFLOW_CONFIGURATIONS_PATH, params={"module": module})
    return validate_response(
        WorkflowConfigurations, endpoint=WORKFLOW_CONFIGURATIONS_PATH, payload=payload
    )


#: Inner transport factory for API reads (tests inject a mock).
TRANSPORT_FACTORY: Callable[[], httpx.BaseTransport] = httpx.HTTPTransport


def live_lint_bundle(
    profile: str,
    *,
    module: str = "Deals",
    max_api_calls: int | None = None,
    transport_factory: Callable[[], httpx.BaseTransport] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], set[str], dict[str, str], dict[str, dict[str, int]]]:
    """Read rules, actions, failures, fields and limits behind *profile*.

    Every workflow endpoint is `unverified`, so this bundle exists only
    behind ``--experimental``; the fields read uses the verified fields
    endpoint. Returns ``(rules_payload, action_maps, field_names,
    failures, limits)``; callers translate with
    :mod:`zohokit.modules.workflow.import_real`. GET-only, budgeted.
    """
    current = load_profile(profile)
    budget = CallBudget(max_calls=max_api_calls or DEFAULT_MAX_API_CALLS)
    dc = DC_TABLE[current.dc]
    factory = transport_factory or TRANSPORT_FACTORY
    manager = TokenManager(dc=current.dc, profile=current.name, transport_factory=factory)
    client = authenticated_client(dc.api_base, manager, budget, factory())
    rules = read_workflow_rules(client, module=module)
    updates = read_field_updates(client)
    emails = read_email_notifications(client)
    tasks = read_automation_tasks(client)
    webhooks = read_webhooks(client)
    failures_page = read_webhook_failures(client)
    configs = read_workflow_configurations(client, module=module)
    field_entries = unwrap_fields(
        read_model(
            client, "/crm/v8/settings/fields", FieldsResponse, params={"module": module}
        ).model_dump(),
        endpoint="/crm/v8/settings/fields",
    )
    field_names = {
        str(entry.get("api_name", "")) for entry in field_entries if entry.get("api_name")
    }
    maps: dict[str, Any] = {
        "field_updates": {
            str(item.get("id", "")): {
                "field": str((item.get("field") or {}).get("api_name", "")),
                "value": (item.get("value") or [None])[0],
            }
            for item in updates.field_updates
            if isinstance(item, dict)
        },
        "emails": {
            str(item.get("id", "")): str(item.get("name", ""))
            for item in emails.email_notifications
            if isinstance(item, dict)
        },
        "tasks": {
            str(item.get("id", "")): str(item.get("name", ""))
            for item in tasks.tasks
            if isinstance(item, dict)
        },
        "webhooks": {
            str(item.get("id", "")): str(item.get("url", ""))
            for item in webhooks.webhooks
            if isinstance(item, dict)
        },
        "functions": {},
    }
    failures = {
        str((item.get("webhook") or {}).get("id", "")): str(item.get("failure_reason", ""))
        for item in failures_page.webhook_failures
        if isinstance(item, dict)
    }
    by_v2: dict[str, int] = {}
    actions_cfg = configs.workflow_configurations.get("actions", [])
    inverse = {real: v2 for v2, real in ACTION_MAP.items()}
    for entry in actions_cfg if isinstance(actions_cfg, list) else []:
        if not isinstance(entry, dict):
            continue
        v2_name = inverse.get(str(entry.get("api_name", "")), "")
        if v2_name and isinstance(entry.get("limit"), int):
            by_v2[v2_name] = int(entry["limit"])
    rules_payload: dict[str, Any] = {
        "workflow_rules": [dict(rule) for rule in rules.workflow_rules]
    }
    return rules_payload, maps, field_names, failures, {module: by_v2}


__all__: list[str] = [
    "AUTOMATION_TASKS_PATH",
    "EMAIL_NOTIFICATIONS_PATH",
    "FIELD_UPDATES_PATH",
    "TRANSPORT_FACTORY",
    "WEBHOOKS_PATH",
    "WEBHOOK_FAILURES_PATH",
    "WORKFLOW_CONFIGURATIONS_PATH",
    "WORKFLOW_RULES_PATH",
    "AutomationTasksPage",
    "EmailNotificationsPage",
    "FieldUpdatesPage",
    "WebhookFailuresPage",
    "WebhooksPage",
    "WorkflowConfigurations",
    "WorkflowRulesPage",
    "live_lint_bundle",
    "read_automation_tasks",
    "read_email_notifications",
    "read_field_updates",
    "read_webhook_failures",
    "read_webhooks",
    "read_workflow_configurations",
    "read_workflow_rule",
    "read_workflow_rules",
]
