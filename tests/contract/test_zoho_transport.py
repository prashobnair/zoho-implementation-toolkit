"""Contract suite: GET-only transport against synthetic cassettes (offline).

Every payload below is hand-written from the official Zoho API docs with
fake IDs and ``example.invalid`` addresses; nothing here ever touched the
network. Runs under ``pytest -m contract --disable-socket`` (STD §3.3).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from zohokit.connectors.zoho.budget import CallBudget
from zohokit.connectors.zoho.client import ZohoClient
from zohokit.connectors.zoho.errors import ConnectorError, ContractDriftError
from zohokit.connectors.zoho.models import (
    FieldsResponse,
    ModulesResponse,
    OrgResponse,
    RecordPage,
    UsersResponse,
    unwrap_fields,
    unwrap_modules,
    unwrap_org,
    unwrap_users,
    validate_response,
)
from zohokit.connectors.zoho.pagination import PaginationOutcome, iter_page_number_pages

CASSETTES = Path(__file__).parent / "cassettes"


def _cassette(name: str) -> dict:
    return json.loads((CASSETTES / name).read_text(encoding="utf-8"))


def _client_for(payloads: dict[str, dict]) -> ZohoClient:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = payloads[request.url.path]
        return httpx.Response(200, json=payload)

    return ZohoClient("https://www.zohoapis.in", transport=httpx.MockTransport(handler))


@pytest.mark.contract
def test_org_identity_contract_from_synthetic_cassette() -> None:
    client = _client_for({"/crm/v8/org": _cassette("crm_org.json")})
    response = client.get("/crm/v8/org", endpoint="/crm/v8/org", experimental=True)
    org = unwrap_org(response.json(), endpoint="/crm/v8/org")
    assert org.company_name == "Marigold Labs"
    assert org.raw_extra == {"country_code": "US", "currency": "US Dollar - USD", "iso_code": "USD"}


@pytest.mark.contract
def test_flat_org_shape_is_contract_drift() -> None:
    """The live 2026-10-02 drift: the real reply is ``{"org": [...]}``, not flat."""
    with pytest.raises(ContractDriftError, match="/crm/v8/org"):
        validate_response(
            OrgResponse,
            endpoint="/crm/v8/org",
            payload={"id": "555000111", "company_name": "Marigold Labs"},
        )


@pytest.mark.contract
def test_modules_fields_users_envelopes_from_synthetic_cassettes() -> None:
    modules = unwrap_modules(_cassette("crm_modules.json"), endpoint="/crm/v8/settings/modules")
    assert [m["api_name"] for m in modules] == ["Leads", "Contacts", "Deals"]
    fields = unwrap_fields(_cassette("crm_fields.json"), endpoint="/crm/v8/settings/fields")
    assert [f["api_name"] for f in fields] == ["Email", "Phone"]
    users = unwrap_users(_cassette("crm_users.json"), endpoint="/crm/v8/users")
    assert [u["status"] for u in users] == ["active"]
    validated = validate_response(
        UsersResponse, endpoint="/crm/v8/users", payload=_cassette("crm_users.json")
    )
    assert validated.info is not None


@pytest.mark.contract
@pytest.mark.parametrize(
    ("model", "endpoint", "payload"),
    [
        (OrgResponse, "/crm/v8/org", {"org": []}),
        (ModulesResponse, "/crm/v8/settings/modules", {"modules": []}),
        (FieldsResponse, "/crm/v8/settings/fields", {"fields": []}),
        (UsersResponse, "/crm/v8/users", {"users": [], "info": {}}),
        (OrgResponse, "/crm/v8/org", {}),
        (ModulesResponse, "/crm/v8/settings/modules", {}),
        (FieldsResponse, "/crm/v8/settings/fields", {}),
        (UsersResponse, "/crm/v8/users", {}),
    ],
)
def test_empty_or_missing_envelope_list_is_contract_drift(
    model: type, endpoint: str, payload: dict
) -> None:
    with pytest.raises(ContractDriftError, match=endpoint):
        validate_response(model, endpoint=endpoint, payload=payload)


@pytest.mark.contract
def test_record_search_pagination_contract_with_budget_cap() -> None:
    pages = _cassette("crm_leads_pages.json")["pages"]

    def fetch(page: int, per_page: int) -> tuple[list[dict], bool]:
        assert per_page == 2
        entry = pages[page - 1]
        validated = validate_response(RecordPage, endpoint="/crm/v8/Leads", payload=entry)
        return (validated.data, validated.more_records)

    budget = CallBudget(max_calls=2)
    outcome = PaginationOutcome()
    records = list(iter_page_number_pages(fetch, budget=budget, outcome=outcome, per_page=2))
    assert [record["Email"] for record in records] == [
        "a***@example.invalid",
        "b***@example.invalid",
        "c***@example.invalid",
        "d***@example.invalid",
    ]
    assert outcome.truncated is True


@pytest.mark.contract
def test_unverified_endpoint_requires_experimental() -> None:
    client = _client_for({"/crm/v8/org": _cassette("crm_org.json")})
    with pytest.raises(ConnectorError, match="unverified"):
        client.get("/crm/v8/org", endpoint="/crm/v8/org")
