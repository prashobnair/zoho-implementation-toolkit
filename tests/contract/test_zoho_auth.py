"""Contract suite: auth exchange + doctor against synthetic cassettes (offline).

Hand-written from the official Zoho API docs (fake tokens, fake IDs,
``example.invalid``); runs under ``pytest -m contract --disable-socket``.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from zohokit.connectors.zoho.auth import AuthTransport, TokenResponse, exchange_grant_code
from zohokit.connectors.zoho.budget import CallBudget
from zohokit.connectors.zoho.client import ZohoClient
from zohokit.connectors.zoho.doctor import doctor_exit_code, run_doctor
from zohokit.connectors.zoho.errors import SafetyGuardError
from zohokit.connectors.zoho.profiles import Profile

CASSETTES = Path(__file__).parent / "cassettes"


@pytest.mark.contract
def test_token_exchange_contract() -> None:
    cassette = json.loads((CASSETTES / "auth_token.json").read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.host == "accounts.zoho.in"
        assert request.url.path == "/oauth/v2/token"
        return httpx.Response(200, json=cassette)

    tokens = exchange_grant_code(
        "fake-grant-code",
        dc="in",
        client_id="fake-id",
        client_secret="fake-secret",
        transport=httpx.MockTransport(handler),
        expected_api_base="https://www.zohoapis.in",
    )
    assert isinstance(tokens, TokenResponse)
    assert tokens.refresh_token == "[redacted-credential]"
    assert tokens.api_domain == "https://www.zohoapis.in"


@pytest.mark.contract
def test_auth_transport_contract_refuses_api_hosts() -> None:
    transport = AuthTransport(httpx.MockTransport(lambda r: httpx.Response(200, json={})), dc="in")
    with pytest.raises(SafetyGuardError):
        transport.handle_request(
            httpx.Request("POST", "https://www.zohoapis.in/crm/v8/Leads", content=b"{}")
        )


@pytest.mark.contract
def test_doctor_contract_against_org_cassette() -> None:
    org = json.loads((CASSETTES / "crm_org.json").read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=org, headers={"date": "Thu, 01 Oct 2026 00:00:00 GMT"})

    def make_client() -> ZohoClient:
        return ZohoClient("https://www.zohoapis.in", transport=httpx.MockTransport(handler))

    profile = Profile(
        name="dev-in",
        dc="in",
        scopes=[
            "ZohoCRM.modules.READ",
            "ZohoCRM.settings.READ",
            "ZohoCRM.users.READ",
            "ZohoCRM.org.READ",
        ],
        environment="developer_edition",
    )
    checks = run_doctor(
        profile,
        client_factory=make_client,
        token_refresher=lambda: True,
        budget=CallBudget(max_calls=200),
        experimental=True,
    )
    assert doctor_exit_code(checks) == 0
    assert next(c for c in checks if c.name == "org_identity").status == "pass"
