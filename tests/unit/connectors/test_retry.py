"""STD-H1: timeouts, retries with backoff + jitter, Retry-After, max 5 attempts."""

from __future__ import annotations

import httpx
import pytest

from zohokit.connectors.zoho.client import ZohoClient
from zohokit.connectors.zoho.errors import ConnectorError
from zohokit.connectors.zoho.retry import RetryPolicy, default_timeouts


def test_default_timeouts_connect_5_read_30() -> None:
    timeouts = default_timeouts()
    assert timeouts.connect == 5.0
    assert timeouts.read == 30.0


def test_retry_after_is_honored_with_deterministic_clock() -> None:
    sleeps: list[float] = []
    script = [
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(200, json={"data": []}),
    ]

    class Scripted(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return script.pop(0)

    policy = RetryPolicy(sleep=sleeps.append, jitter=lambda: 0.0)
    client = ZohoClient(
        "https://www.zohoapis.in",
        transport=Scripted(),
        retry=policy,
    )
    response = client.get("/crm/v8/Leads", experimental=True)
    assert response.status_code == 200
    assert sleeps == [2.0]


def test_backoff_grows_and_stops_after_five_attempts() -> None:
    sleeps: list[float] = []
    calls = 0

    class AlwaysDown(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(503, json={})

    policy = RetryPolicy(base_delay=0.5, max_delay=8.0, sleep=sleeps.append, jitter=lambda: 0.0)
    client = ZohoClient("https://www.zohoapis.in", transport=AlwaysDown(), retry=policy)
    response = client.get("/crm/v8/Leads", experimental=True)
    assert response.status_code == 503
    assert calls == 5
    assert sleeps == [0.5, 1.0, 2.0, 4.0]


def test_connection_reset_is_retried_then_recovers() -> None:
    attempts = 0

    class Flaky(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise httpx.ConnectError("connection reset by peer")
            return httpx.Response(200, json={"data": []})

    client = ZohoClient(
        "https://www.zohoapis.in",
        transport=Flaky(),
        retry=RetryPolicy(sleep=lambda _: None, jitter=lambda: 0.0),
    )
    assert client.get("/crm/v8/Leads", experimental=True).status_code == 200
    assert attempts == 2


def test_non_retryable_status_is_not_retried() -> None:
    calls = 0

    class Bad(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(400, json={})

    client = ZohoClient(
        "https://www.zohoapis.in",
        transport=Bad(),
        retry=RetryPolicy(sleep=lambda _: None, jitter=lambda: 0.0),
    )
    assert client.get("/crm/v8/Leads", experimental=True).status_code == 400
    assert calls == 1


def test_persistent_connection_failure_raises_connector_error() -> None:
    class Down(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

    client = ZohoClient(
        "https://www.zohoapis.in",
        transport=Down(),
        retry=RetryPolicy(sleep=lambda _: None, jitter=lambda: 0.0),
    )
    with pytest.raises(ConnectorError):
        client.get("/crm/v8/Leads", experimental=True)
