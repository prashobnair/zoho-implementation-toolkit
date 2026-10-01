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
from zohokit.connectors.zoho.errors import ConnectorError
from zohokit.connectors.zoho.models import OrgInfo, RecordPage, validate_response
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
    org = validate_response(OrgInfo, endpoint="/crm/v8/org", payload=response.json())
    assert org.company_name == "Marigold Labs"
    assert org.raw_extra == {}


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
