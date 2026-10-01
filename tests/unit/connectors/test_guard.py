"""STD-L1: the GET-only guard rejects every write path before any byte is sent."""

from __future__ import annotations

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from zohokit.connectors.zoho.client import ZohoClient
from zohokit.connectors.zoho.errors import SafetyGuardError


class RecordingTransport(httpx.BaseTransport):
    """Counts requests that reach the (mock) network."""

    def __init__(self) -> None:
        self.calls = 0
        self.seen_headers: list[dict[str, str]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        self.seen_headers.append(dict(request.headers))
        return httpx.Response(200, json={"data": [], "more_records": False})


def _client(recording: RecordingTransport) -> ZohoClient:
    return ZohoClient("https://www.zohoapis.in", transport=recording)


def _authed_client(recording: RecordingTransport) -> ZohoClient:
    return ZohoClient(
        "https://www.zohoapis.in",
        transport=recording,
        token_provider=lambda: "secret-token-123",
    )


def test_get_is_allowed() -> None:
    recording = RecordingTransport()
    response = _client(recording).get("/crm/v8/org", experimental=True)
    assert response.status_code == 200
    assert recording.calls == 1


def test_head_is_allowed() -> None:
    recording = RecordingTransport()
    response = _client(recording).head("/crm/v8/org", experimental=True)
    assert response.status_code == 200
    assert recording.calls == 1


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "post", "Post"])
def test_non_get_methods_raise_before_send(method: str) -> None:
    recording = RecordingTransport()
    client = _client(recording)
    with pytest.raises(SafetyGuardError):
        client.request(method, "/crm/v8/Leads", experimental=True)
    assert recording.calls == 0


@pytest.mark.parametrize("header", ["X-HTTP-Method-Override", "x-http-method", "X-Method-Override"])
def test_override_headers_rejected(header: str) -> None:
    recording = RecordingTransport()
    client = _client(recording)
    with pytest.raises(SafetyGuardError):
        client.get("/crm/v8/org", headers={header: "POST"}, experimental=True)
    assert recording.calls == 0


def test_method_query_param_rejected() -> None:
    recording = RecordingTransport()
    client = _client(recording)
    with pytest.raises(SafetyGuardError):
        client.get("/crm/v8/org", params={"_method": "DELETE"}, experimental=True)
    assert recording.calls == 0


def test_get_with_body_rejected() -> None:
    recording = RecordingTransport()
    client = _client(recording)
    request = httpx.Request("GET", "https://www.zohoapis.in/crm/v8/org", content=b'{"s": 1}')
    with pytest.raises(SafetyGuardError):
        client.send(request)
    assert recording.calls == 0


def test_send_of_built_post_rejected() -> None:
    recording = RecordingTransport()
    client = _client(recording)
    request = httpx.Request("POST", "https://www.zohoapis.in/crm/v8/Leads")
    with pytest.raises(SafetyGuardError):
        client.send(request)
    assert recording.calls == 0


def test_stream_guards_method() -> None:
    recording = RecordingTransport()
    client = _client(recording)
    with pytest.raises(SafetyGuardError):
        with client.stream("POST", "/crm/v8/Leads", experimental=True):
            pass
    assert recording.calls == 0


def test_stream_get_flows_through_guard() -> None:
    recording = RecordingTransport()
    client = _client(recording)
    with client.stream("GET", "/crm/v8/org", experimental=True) as response:
        assert response.status_code == 200
    assert recording.calls == 1


def test_no_public_writable_client_exposed() -> None:
    client = _client(RecordingTransport())
    for name in ("client", "http", "httpx_client", "_client", "session", "transport", "get_client"):
        assert not hasattr(client, name), f"ZohoClient must not expose {name!r}"
    assert "client" not in dir(client)
    assert "http" not in dir(client)


@given(
    method=st.sampled_from(["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"]),
    header_name=st.sampled_from(
        ["X-HTTP-Method-Override", "x-http-method-override", "X-Http-Method", "X-METHOD-OVERRIDE"]
    ),
    path_form=st.sampled_from(["/crm/v8/org", "/crm/v8/org/", "/crm/v8/Leads?fields=Name"]),
)
def test_hypothesis_write_shapes_always_blocked(
    method: str, header_name: str, path_form: str
) -> None:
    recording = RecordingTransport()
    client = _client(recording)
    # Plain non-GET method is blocked on its own.
    with pytest.raises(SafetyGuardError):
        client.request(method, "/crm/v8/Leads", experimental=True)
    # Override header on an otherwise-legal GET is blocked whatever the casing.
    with pytest.raises(SafetyGuardError):
        client.get(path_form, headers={header_name: "GET"}, experimental=True)
    assert recording.calls == 0


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/collect",
        "http://www.zohoapis.in/crm/v8/org",
        "https://www.zohoapis.in:8443/crm/v8/org",
        "https://user@www.zohoapis.in/crm/v8/org",
        "https://127.0.0.1/crm/v8/org",
    ],
)
def test_credential_confinement_blocks_exfiltration(url: str) -> None:
    """Token-bearing requests never leave the allowlisted https API host."""
    recording = RecordingTransport()
    client = _authed_client(recording)
    with pytest.raises(SafetyGuardError):
        client.get(url, experimental=True)
    assert recording.calls == 0
    assert recording.seen_headers == []
    # The built request itself must not carry the token either.
    pending = client.build_request("GET", url)
    assert "authorization" not in {name.lower() for name in pending.headers}


def test_authed_get_to_allowlisted_host_sends_token() -> None:
    recording = RecordingTransport()
    response = _authed_client(recording).get("/crm/v8/org", experimental=True)
    assert response.status_code == 200
    assert recording.calls == 1
    assert recording.seen_headers[0].get("authorization") == "Zoho-oauthtoken secret-token-123"


def test_api_domain_registration_trusts_only_zoho() -> None:
    recording = RecordingTransport()
    client = _authed_client(recording)
    assert client.register_api_domain("https://crm.zoho.com") == "crm.zoho.com"
    response = client.get("https://crm.zoho.com/crm/v8/org", experimental=True)
    assert response.status_code == 200
    with pytest.raises(SafetyGuardError):
        client.register_api_domain("https://evil.example/collect")


@pytest.mark.parametrize("param", ["_METHOD", "_Method", "%5FMETHOD", "%5Fmethod"])
def test_method_param_name_is_case_insensitive(param: str) -> None:
    recording = RecordingTransport()
    client = _client(recording)
    with pytest.raises(SafetyGuardError):
        client.get(f"/crm/v8/org?{param}=DELETE", experimental=True)
    assert recording.calls == 0


def test_head_with_body_is_blocked() -> None:
    recording = RecordingTransport()
    client = _client(recording)
    request = httpx.Request("HEAD", "https://www.zohoapis.in/crm/v8/org", content=b"x")
    with pytest.raises(SafetyGuardError):
        client.send(request)
    assert recording.calls == 0


def test_get_with_streamed_body_is_guard_violation() -> None:
    recording = RecordingTransport()
    client = _client(recording)
    request = httpx.Request("GET", "https://www.zohoapis.in/crm/v8/org", content=iter([b"a"]))
    with pytest.raises(SafetyGuardError):
        client.send(request)
    assert recording.calls == 0
