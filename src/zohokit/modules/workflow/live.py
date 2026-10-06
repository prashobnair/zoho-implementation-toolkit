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

from typing import Any

from pydantic import Field

from zohokit.connectors.zoho.client import ZohoClient
from zohokit.connectors.zoho.errors import ContractDriftError
from zohokit.connectors.zoho.models import ZohoResponse, validate_response
from zohokit.connectors.zoho.readers import raise_for_zoho_error

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


__all__: list[str] = [
    "AUTOMATION_TASKS_PATH",
    "EMAIL_NOTIFICATIONS_PATH",
    "FIELD_UPDATES_PATH",
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
    "read_automation_tasks",
    "read_email_notifications",
    "read_field_updates",
    "read_webhook_failures",
    "read_webhooks",
    "read_workflow_configurations",
    "read_workflow_rule",
    "read_workflow_rules",
]
