"""Shared readers: one org parser, parameterised record reads, Zoho errors.

Regression suite for live run 3: doctor's org check and the smoke org read
both funnel through :func:`read_org`, record reads always send the v8
mandatory ``fields`` parameter, HTTP 204 is a valid empty page, and Zoho
error bodies map to :class:`ConnectorError` carrying the Zoho code only.
"""

from __future__ import annotations

import httpx
import pytest

from zohokit.connectors.zoho.budget import CallBudget
from zohokit.connectors.zoho.client import ZohoClient
from zohokit.connectors.zoho.doctor import org_fingerprint, run_doctor
from zohokit.connectors.zoho.errors import ConnectorError, ContractDriftError
from zohokit.connectors.zoho.models import RecordPage, validate_response
from zohokit.connectors.zoho.profiles import Profile
from zohokit.connectors.zoho.readers import (
    RECORD_FIELDS,
    read_org,
    read_records,
)

RECORDED_ORG = {"org": [{"id": "555000111", "company_name": "Marigold Labs"}]}


def _client(handler: object) -> ZohoClient:
    return ZohoClient(
        "https://www.zohoapis.in",
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    )


def _profile() -> Profile:
    return Profile.model_validate(
        {
            "name": "dev-in",
            "dc": "in",
            "scopes": [
                "ZohoCRM.modules.READ",
                "ZohoCRM.settings.READ",
                "ZohoCRM.users.READ",
                "ZohoCRM.org.READ",
            ],
            "environment": "developer_edition",
        }
    )


def test_doctor_and_smoke_share_one_org_reader() -> None:
    """The same recorded-shape payload gives identical results on both paths."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/crm/v8/org"
        return httpx.Response(
            200,
            json=RECORDED_ORG,
            headers={"date": "Thu, 01 Oct 2026 00:00:00 GMT"},
        )

    # Smoke path: the shared reader directly.
    read = read_org(_client(handler), experimental=True)
    assert read.org.id == "555000111"
    assert read.date_header == "Thu, 01 Oct 2026 00:00:00 GMT"

    # Doctor path: run_doctor's org_identity check over the same payload.
    checks = run_doctor(
        _profile(),
        client_factory=lambda: _client(handler),
        token_refresher=lambda: True,
        budget=CallBudget(max_calls=200),
        experimental=True,
    )
    org_check = next(check for check in checks if check.name == "org_identity")
    assert org_check.status == "pass"
    assert org_check.detail == f"org {org_fingerprint(read.org.id)}"
    assert "555000111" not in org_check.detail


def test_unauthenticated_org_error_is_connector_error_not_drift() -> None:
    """A 401 error body (no ``org`` key) maps to ConnectorError with the code."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return httpx.Response(
            401,
            json={
                "code": "INVALID_TOKEN",
                "status": "error",
                "message": "invalid oauth token",
                "details": {},
            },
        )

    with pytest.raises(ConnectorError, match="INVALID_TOKEN"):
        read_org(_client(handler), experimental=True)
    with pytest.raises(ConnectorError) as exc_info:
        read_org(_client(handler), experimental=True)
    assert "contract_drift" not in str(exc_info.value)


def test_record_read_sends_mandatory_fields_param() -> None:
    """v8 requires ``fields``: the client sends id + Created_Time + name field."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(
            200,
            json={
                "data": [{"id": "555000001", "Last_Name": "Marigold"}],
                "info": {"more_records": True, "count": 1, "page": 1, "per_page": 5},
            },
        )

    page = read_records(_client(handler), "Leads", experimental=True)
    assert seen["fields"] == ",".join(RECORD_FIELDS["Leads"])
    assert "Created_Time" in seen["fields"].split(",")
    assert seen["page"] == "1"
    assert [record["id"] for record in page.data] == ["555000001"]
    assert page.more_records is True


def test_record_page_with_info_more_records() -> None:
    """A page with records reports ``info.more_records`` (nested, per the docs)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "555000001", "Last_Name": "Alpha"},
                    {"id": "555000002", "Last_Name": "Beta"},
                ],
                "info": {"more_records": False, "count": 2, "page": 1, "per_page": 5},
            },
        )

    page = read_records(_client(handler), "Contacts", experimental=True)
    assert len(page.data) == 2
    assert page.more_records is False
    assert page.next_page_token is None


def test_record_empty_module_204_is_valid_empty_page() -> None:
    """HTTP 204 with an empty body is 0 records, not drift."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(204)

    page = read_records(_client(handler), "Deals", experimental=True)
    assert calls == 1
    assert page.data == []
    assert page.more_records is False


def test_record_missing_fields_rejected_before_send() -> None:
    """An empty field list fails client-side: nothing is sent, budget kept."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": [], "info": {"more_records": False}})

    budget = CallBudget(max_calls=200)
    client = ZohoClient(
        "https://www.zohoapis.in", transport=httpx.MockTransport(handler), budget=budget
    )
    with pytest.raises(ConnectorError, match="fields"):
        read_records(client, "Leads", fields=[], experimental=True)
    assert calls == 0
    assert budget.used == 0


def test_record_400_required_param_missing_is_connector_error_with_code_only() -> None:
    """A 400 Zoho error body carries the code only — never values, never drift."""
    sneaky_email = "amara.okafor@example.com"
    sneaky_phone = "+1 415-860-1234"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "code": "REQUIRED_PARAM_MISSING",
                "status": "error",
                "message": f"contact {sneaky_email} {sneaky_phone}",
                "details": {"api_name": sneaky_email},
            },
        )

    with pytest.raises(ConnectorError) as exc_info:
        read_records(_client(handler), "Leads", experimental=True)
    message = str(exc_info.value)
    assert "REQUIRED_PARAM_MISSING" in message
    assert "/crm/v8/Leads" in message
    assert "contract_drift" not in message
    assert sneaky_email not in message
    assert sneaky_phone not in message


def test_record_error_without_code_falls_back_to_http_status() -> None:
    """A codeless 500 stays value-free (endpoint + HTTP status only)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"status": "error", "message": "boom 555000111"})

    with pytest.raises(ConnectorError) as exc_info:
        read_records(_client(handler), "Leads", experimental=True)
    message = str(exc_info.value)
    assert "500" in message
    assert "boom" not in message
    assert "555000111" not in message


def test_record_contract_errors_stay_value_free() -> None:
    """A 200 payload missing ``data`` is drift naming endpoint + location only."""
    with pytest.raises(ContractDriftError) as exc_info:
        validate_response(
            RecordPage,
            endpoint="/crm/v8/Leads",
            payload={"info": {"more_records": False}},
        )
    message = str(exc_info.value)
    assert "/crm/v8/Leads" in message
    assert "data" in message
