"""Self Client auth: grant exchange over a POST-only transport (STD-A1..A4).

The token exchange is the ONLY non-GET allowed anywhere in the toolkit.
It goes through :class:`AuthTransport`, a minimal transport that can ONLY
POST to ``https://accounts.zoho.<tld>/oauth/v2/token`` (exact host
allowlist, exact path) and is never used for API calls.
"""

from __future__ import annotations

import os
import threading
import time
import warnings
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from zohokit.connectors.zoho.dc import DC_TABLE, TOKEN_PATH
from zohokit.connectors.zoho.errors import ConnectorError, SafetyGuardError

# Environment variable NAMES (not values) for the CI credential fallback.
REFRESH_TOKEN_ENV = "ZOHO_REFRESH_TOKEN"  # nosec B105
CLIENT_ID_ENV = "ZOHO_CLIENT_ID"  # nosec B105
CLIENT_SECRET_ENV = "ZOHO_CLIENT_SECRET"  # nosec B105
KEYRING_SERVICE = "zohokit"


class TokenResponse(BaseModel):
    """Token endpoint reply (synthetic shape, unverified)."""

    model_config = ConfigDict(extra="allow")

    refresh_token: str = ""
    access_token: str = ""
    api_domain: str = ""
    expires_in: int = 3600


class AuthTransport(httpx.BaseTransport):
    """POST-only transport pinned to the accounts token endpoint."""

    def __init__(self, inner: httpx.BaseTransport, *, dc: str) -> None:
        if dc not in DC_TABLE:
            raise ValueError(f"unknown DC {dc!r}")
        self._inner = inner
        self._host = DC_TABLE[dc].accounts_host

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if (
            request.method.upper() != "POST"
            or url.host != self._host
            or url.scheme != "https"
            or url.path != TOKEN_PATH
        ):
            raise SafetyGuardError(
                f"auth transport refused {request.method} {url}: "
                f"only POST https://{self._host}{TOKEN_PATH} is allowed"
            )
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


def exchange_grant_code(
    grant_code: str,
    *,
    dc: str,
    client_id: str,
    client_secret: str,
    transport: httpx.BaseTransport,
    expected_api_base: str = "",
) -> TokenResponse:
    """Exchange a Self Client grant code for tokens (synthetic in tests)."""
    client = httpx.Client(transport=AuthTransport(transport, dc=dc), timeout=30.0)
    try:
        response = client.post(
            f"https://{DC_TABLE[dc].accounts_host}{TOKEN_PATH}",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "code": grant_code,
            },
        )
    finally:
        client.close()
    if response.status_code != 200:
        raise ConnectorError(f"token exchange failed with HTTP {response.status_code}")
    payload = TokenResponse.model_validate(response.json())
    if not payload.refresh_token:
        raise ConnectorError("token exchange returned no refresh_token")
    if (
        expected_api_base
        and payload.api_domain
        and payload.api_domain.rstrip("/") != expected_api_base
    ):
        warnings.warn(
            f"api_domain {payload.api_domain!r} differs from profile base "
            f"{expected_api_base!r}; honoring the token response",
            UserWarning,
            stacklevel=2,
        )
    return payload


def refresh_access_token(
    refresh_token: str,
    *,
    dc: str,
    client_id: str,
    client_secret: str,
    transport: httpx.BaseTransport,
) -> TokenResponse:
    """Exchange a refresh token for a fresh access token."""
    client = httpx.Client(transport=AuthTransport(transport, dc=dc), timeout=30.0)
    try:
        response = client.post(
            f"https://{DC_TABLE[dc].accounts_host}{TOKEN_PATH}",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
        )
    finally:
        client.close()
    if response.status_code != 200:
        raise ConnectorError(f"token refresh failed with HTTP {response.status_code}")
    payload = TokenResponse.model_validate(response.json())
    if not payload.access_token:
        raise ConnectorError("token refresh returned no access_token")
    return payload


def store_refresh_token(profile: str, token: str) -> None:
    """Persist the refresh token in the OS keyring (STD-A1)."""
    import keyring

    keyring.set_password(KEYRING_SERVICE, f"{profile}:refresh_token", token)


def read_refresh_token(profile: str) -> str | None:
    """Refresh token from the OS keyring, else the CI fallback env var."""
    try:
        import keyring

        token = keyring.get_password(KEYRING_SERVICE, f"{profile}:refresh_token")
    except Exception:
        token = None
    if token:
        return token
    fallback = os.environ.get(REFRESH_TOKEN_ENV)
    return fallback or None


def store_client_secret(profile: str, kind: str, value: str) -> None:
    """Persist a client id/secret in the OS keyring (never in repo files)."""
    import keyring

    keyring.set_password(KEYRING_SERVICE, f"{profile}:{kind}", value)


def read_client_secret(profile: str, kind: str) -> str | None:
    """Client id/secret from the OS keyring, else the env fallback."""
    try:
        import keyring

        value = keyring.get_password(KEYRING_SERVICE, f"{profile}:{kind}")
    except Exception:
        value = None
    if value:
        return value
    env_name = CLIENT_ID_ENV if kind == "client_id" else CLIENT_SECRET_ENV
    return os.environ.get(env_name)


class TokenManager:
    """In-memory access tokens with refresh-once single-flight semantics (STD-A3)."""

    def __init__(
        self,
        *,
        dc: str,
        profile: str,
        transport_factory: Callable[[], httpx.BaseTransport],
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._dc = dc
        self._profile = profile
        self._transport_factory = transport_factory
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self.refresh_count = 0

    def token_provider(self) -> str | None:
        """Return the cached access token for the GET-only client."""
        return self._access_token

    def ensure_fresh(self) -> str:
        """Return a live access token, refreshing once behind a lock."""
        if self._access_token and self._clock() < self._expires_at - 60.0:
            return self._access_token
        with self._lock:
            if self._access_token and self._clock() < self._expires_at - 60.0:
                return self._access_token
            return self._refresh_locked()

    def _refresh_locked(self) -> str:
        refresh_token = read_refresh_token(self._profile)
        client_id = read_client_secret(self._profile, "client_id")
        client_secret = read_client_secret(self._profile, "client_secret")
        if not refresh_token or not client_id or not client_secret:
            raise ConnectorError(
                f"profile {self._profile!r} has no stored credentials: "
                "run `zohokit auth login` or set ZOHO_REFRESH_TOKEN"
            )
        payload = refresh_access_token(
            refresh_token,
            dc=self._dc,
            client_id=client_id,
            client_secret=client_secret,
            transport=self._transport_factory(),
        )
        self._access_token = payload.access_token
        self._expires_at = self._clock() + float(payload.expires_in)
        self.refresh_count += 1
        return self._access_token

    def authorized_send(
        self, send: Callable[[str | None], Any], *, is_invalid_token: Callable[[Any], bool]
    ) -> Any:
        """Send with the current token; on 401 INVALID_TOKEN refresh once and retry."""
        token = self._access_token or self.ensure_fresh()
        response = send(token)
        if is_invalid_token(response):
            with self._lock:
                self._access_token = None
                token = self._refresh_locked()
            response = send(token)
        return response


__all__: list[str] = [
    "CLIENT_ID_ENV",
    "CLIENT_SECRET_ENV",
    "KEYRING_SERVICE",
    "REFRESH_TOKEN_ENV",
    "AuthTransport",
    "TokenManager",
    "TokenResponse",
    "exchange_grant_code",
    "read_client_secret",
    "read_refresh_token",
    "refresh_access_token",
    "store_client_secret",
    "store_refresh_token",
]
