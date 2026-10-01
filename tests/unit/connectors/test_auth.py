"""STD-A1..A4: Self Client exchange over the POST-only auth transport."""

from __future__ import annotations

import threading

import httpx
import pytest

from zohokit.connectors.zoho.auth import (
    AuthTransport,
    TokenManager,
    TokenResponse,
    exchange_grant_code,
    read_client_secret,
    read_refresh_token,
    refresh_access_token,
    store_client_secret,
    store_refresh_token,
)
from zohokit.connectors.zoho.dc import DC_TABLE, token_url
from zohokit.connectors.zoho.errors import ConnectorError, SafetyGuardError


@pytest.fixture()
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Dict-backed keyring so tests never touch the OS store."""
    vault: dict[str, str] = {}

    def fake_set(service: str, key: str, value: str) -> None:
        vault[f"{service}:{key}"] = value

    def fake_get(service: str, key: str) -> str | None:
        return vault.get(f"{service}:{key}")

    monkeypatch.setattr("keyring.set_password", fake_set)
    monkeypatch.setattr("keyring.get_password", fake_get)
    return vault


def _token_handler(request: httpx.Request) -> httpx.Response:
    body = dict(httpx.QueryParams(request.content.decode()))
    if body.get("grant_type") == "authorization_code":
        assert body["code"] == "fake-grant-code"
        return httpx.Response(
            200,
            json={
                "refresh_token": "fake.refresh.token",
                "access_token": "fake.access.token",
                "api_domain": "https://www.zohoapis.in",
                "expires_in": 3600,
            },
        )
    assert body.get("grant_type") == "refresh_token"
    return httpx.Response(
        200,
        json={
            "access_token": "fake.access.token.2",
            "api_domain": "https://www.zohoapis.in",
            "expires_in": 3600,
        },
    )


def _mock() -> httpx.MockTransport:
    return httpx.MockTransport(_token_handler)


def test_token_url_covers_all_seven_dcs() -> None:
    assert sorted(DC_TABLE) == ["au", "ca", "cn", "eu", "in", "jp", "us"]
    assert token_url("in") == "https://accounts.zoho.in/oauth/v2/token"
    assert token_url("ca") == "https://accounts.zohocloud.ca/oauth/v2/token"


def test_auth_transport_allows_only_token_post(fake_keyring: dict[str, str]) -> None:
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    transport = AuthTransport(httpx.MockTransport(ok), dc="in")
    client = httpx.Client(transport=transport)
    try:
        response = client.post("https://accounts.zoho.in/oauth/v2/token", data={"grant_type": "x"})
        assert response.status_code == 200
    finally:
        client.close()


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "https://accounts.zoho.in/oauth/v2/token"),
        ("POST", "https://accounts.zoho.in/oauth/v2/other"),
        ("POST", "https://accounts.zoho.eu/oauth/v2/token"),
        ("POST", "http://accounts.zoho.in/oauth/v2/token"),
        ("POST", "https://evil.example.invalid/oauth/v2/token"),
        ("DELETE", "https://accounts.zoho.in/oauth/v2/token"),
    ],
)
def test_auth_transport_refuses_everything_else(method: str, url: str) -> None:
    transport = AuthTransport(_mock(), dc="in")
    if method == "POST" and "evil" in url:
        request = httpx.Request(method, url)
    else:
        request = httpx.Request(method, url)
    with pytest.raises(SafetyGuardError):
        transport.handle_request(request)


def test_grant_exchange_stores_refresh_token(fake_keyring: dict[str, str]) -> None:
    payload = exchange_grant_code(
        "fake-grant-code",
        dc="in",
        client_id="fake-id",
        client_secret="fake-secret",
        transport=_mock(),
        expected_api_base="https://www.zohoapis.in",
    )
    assert isinstance(payload, TokenResponse)
    store_refresh_token("dev-in", payload.refresh_token)
    assert read_refresh_token("dev-in") == "fake.refresh.token"


def test_api_domain_mismatch_warns_but_honors_response() -> None:
    with pytest.warns(UserWarning, match="api_domain"):
        payload = exchange_grant_code(
            "fake-grant-code",
            dc="in",
            client_id="fake-id",
            client_secret="fake-secret",
            transport=_mock(),
            expected_api_base="https://www.zohoapis.eu",
        )
    assert payload.api_domain == "https://www.zohoapis.in"


def test_ci_fallback_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZOHO_REFRESH_TOKEN", "env-fallback-token")
    assert read_refresh_token("no-such-profile") == "env-fallback-token"


def test_client_secrets_only_from_keyring_or_env(
    fake_keyring: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store_client_secret("dev-in", "client_id", "kid")
    store_client_secret("dev-in", "client_secret", "ksecret")
    assert read_client_secret("dev-in", "client_id") == "kid"
    monkeypatch.setenv("ZOHO_CLIENT_ID", "env-id")
    assert read_client_secret("other", "client_id") == "env-id"
    assert read_client_secret("other", "client_secret") is None


def test_single_flight_refresh_happens_once(
    fake_keyring: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store_refresh_token("dev-in", "fake.refresh.token")
    store_client_secret("dev-in", "client_id", "kid")
    store_client_secret("dev-in", "client_secret", "ksecret")
    calls = 0
    inner = _mock()

    def counting_factory() -> httpx.BaseTransport:
        nonlocal calls
        calls += 1
        return inner

    manager = TokenManager(dc="in", profile="dev-in", transport_factory=counting_factory)
    results = [None] * 8

    def worker(slot: int) -> None:
        results[slot] = manager.ensure_fresh()

    threads = [threading.Thread(target=worker, args=(slot,)) for slot in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert set(results) == {"fake.access.token.2"}
    assert manager.refresh_count == 1


def test_refresh_once_on_invalid_token(fake_keyring: dict[str, str]) -> None:
    store_refresh_token("dev-in", "fake.refresh.token")
    store_client_secret("dev-in", "client_id", "kid")
    store_client_secret("dev-in", "client_secret", "ksecret")
    manager = TokenManager(dc="in", profile="dev-in", transport_factory=_mock)
    manager.ensure_fresh()
    assert manager.refresh_count == 1
    seen: list[str | None] = []

    def send(token: str | None) -> dict:
        seen.append(token)
        if len(seen) == 1:
            return {"status": 401, "code": "INVALID_TOKEN"}
        return {"status": 200, "code": "OK"}

    outcome = manager.authorized_send(
        send, is_invalid_token=lambda r: r["status"] == 401 and r["code"] == "INVALID_TOKEN"
    )
    assert outcome["status"] == 200
    assert manager.refresh_count == 2
    assert seen[0] == seen[1] == "fake.access.token.2"


def test_exchange_failure_is_connector_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_code"})

    with pytest.raises(ConnectorError, match="token exchange failed"):
        exchange_grant_code(
            "bad-code",
            dc="in",
            client_id="kid",
            client_secret="ksecret",
            transport=httpx.MockTransport(handler),
        )


def test_missing_access_token_is_connector_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    with pytest.raises(ConnectorError, match="no access_token"):
        refresh_access_token(
            "x", dc="in", client_id="k", client_secret="s", transport=httpx.MockTransport(handler)
        )
