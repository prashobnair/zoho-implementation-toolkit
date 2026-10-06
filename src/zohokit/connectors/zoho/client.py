"""One GET-only ``ZohoClient`` for every Zoho call (STD-L1, STD-H1, STD-L5, STD-C2).

The guard lives at the httpx transport layer (:mod:`guard`), so every
path — :meth:`request`, :meth:`get`, :meth:`head`, :meth:`stream`,
:meth:`send`, and ``build_request`` + ``send`` — is covered by
construction. The underlying httpx client is never exposed: there is no
public attribute or getter that returns it.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, cast

import httpx

from zohokit.connectors.zoho.budget import DEFAULT_MAX_API_CALLS, CallBudget
from zohokit.connectors.zoho.errors import ConnectorError, SafetyGuardError
from zohokit.connectors.zoho.guard import (
    GetOnlyTransport,
    api_host_from_url,
    check_request,
    check_url_allowed,
)
from zohokit.connectors.zoho.retry import RetryPolicy, default_timeouts

#: Endpoints confirmed against the live Developer Edition org
#: (``docs/evidence/2026-10-03/``). These call without ``experimental``;
#: every other endpoint stays ``unverified`` and keeps the gate.
#: Single source of truth: :data:`ENDPOINT_STATUS` is derived from this
#: set, and the ``docs/API_CONTRACTS.md`` status column is tested against
#: it (see ``tests/contract/test_live_replay.py``).
VERIFIED_ENDPOINTS: frozenset[str] = frozenset(
    {
        "/crm/v8/org",
        "/crm/v8/settings/modules",
        "/crm/v8/settings/fields",
        "/crm/v8/Leads",
        "/crm/v8/Contacts",
        "/crm/v8/Deals",
        "/crm/v8/users",
    }
)

#: Endpoint call status (STD-C1/C2). Endpoints in
#: :data:`VERIFIED_ENDPOINTS` were read live and validated; anything else
#: is hand-written from the official Zoho API docs with synthetic
#: cassettes, and therefore gated behind ``experimental=True``.
_KNOWN_ENDPOINTS: tuple[str, ...] = (
    "/crm/v8/org",
    "/crm/v8/settings/modules",
    "/crm/v8/settings/fields",
    "/crm/v8/Leads",
    "/crm/v8/Contacts",
    "/crm/v8/Deals",
    "/crm/v8/users",
    "/crm/v8/settings/automation/workflow_rules",
    "/crm/v8/settings/automation/field_updates",
    "/crm/v8/settings/automation/email_notifications",
    "/crm/v8/settings/automation/tasks",
    "/crm/v8/settings/automation/webhooks",
    "/crm/v8/settings/automation/webhook_failures",
    "/crm/v8/workflow_configurations",
)

ENDPOINT_STATUS: dict[str, str] = {
    endpoint: ("verified" if endpoint in VERIFIED_ENDPOINTS else "unverified")
    for endpoint in _KNOWN_ENDPOINTS
}

_EXPERIMENTAL_WARNING = (
    "endpoint {endpoint} is unverified (synthetic cassette only); "
    "called behind --experimental and may drift against the real API"
)


def _check_experimental(endpoint: str | None, *, experimental: bool) -> None:
    status = ENDPOINT_STATUS.get(endpoint or "", "unverified") if endpoint else "unverified"
    if status == "verified":
        return
    if not experimental:
        raise ConnectorError(
            f"endpoint {endpoint or '<unknown>'} is unverified: pass experimental=True "
            "(--experimental) to call it; see docs/API_CONTRACTS.md"
        )
    warnings.warn(_EXPERIMENTAL_WARNING.format(endpoint=endpoint), UserWarning, stacklevel=4)


class ZohoClient:
    """Read-only HTTP client for Zoho APIs."""

    _http: httpx.Client
    _retry: RetryPolicy
    _budget: CallBudget
    _token_provider: Callable[[], str | None] | None
    base_url: str
    _allowed_hosts: set[str]

    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.BaseTransport | None = None,
        token_provider: Callable[[], str | None] | None = None,
        retry: RetryPolicy | None = None,
        budget: CallBudget | None = None,
    ) -> None:
        base_host = httpx.URL(base_url).host or ""
        self._allowed_hosts = {base_host.casefold()} if base_host else set()
        self._http = httpx.Client(
            base_url=base_url,
            transport=GetOnlyTransport(
                transport or httpx.HTTPTransport(), allowed_hosts=self._allowed_hosts
            ),
            timeout=default_timeouts(),
        )
        self._retry = retry or RetryPolicy()
        self._budget = budget or CallBudget(max_calls=DEFAULT_MAX_API_CALLS)
        self._token_provider = token_provider
        self.base_url = base_url.rstrip("/")

    @property
    def allowed_hosts(self) -> frozenset[str]:
        """Allowlisted API hosts for this client (lowercased)."""
        return frozenset(self._allowed_hosts)

    def register_api_domain(self, api_domain: str) -> str:
        """Allowlist an ``api_domain`` from a token response (validated)."""
        normalized = api_host_from_url(api_domain)
        self._allowed_hosts.add(normalized)
        return normalized

    def _url_allows_credentials(self, url: httpx.URL, method: str) -> bool:
        if method.upper() not in ("GET", "HEAD"):
            return False
        try:
            check_url_allowed(url, self._allowed_hosts)
        except SafetyGuardError:
            return False
        return True

    def _strip_credentials_unless_allowed(self, request: httpx.Request) -> None:
        if not self._url_allows_credentials(request.url, request.method):
            for name in [name for name in request.headers if name.lower() == "authorization"]:
                del request.headers[name]

    def _headers(self) -> dict[str, str]:
        provider = self._token_provider
        token = provider() if provider is not None else None
        if token:
            return {"Authorization": f"Zoho-oauthtoken {token}"}
        return {}

    def build_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Request:
        """Build (but do not send) a request for *method* + *path*."""
        # Build without credentials first so the target URL is known, then
        # attach the token only when the method + URL may carry it. Any
        # caller-supplied Authorization header is likewise dropped unless
        # the target is allowlisted (defence in depth).
        caller_auth: tuple[str, str] | None = None
        user_headers: dict[str, str] = {}
        for name, value in (headers or {}).items():
            if name.lower() == "authorization":
                if caller_auth is None:
                    caller_auth = (name, value)
            else:
                user_headers[name] = value
        built = self._http.build_request(method, path, params=params, headers=user_headers)
        request = cast(httpx.Request, built)  # type: ignore[redundant-cast]
        if self._url_allows_credentials(request.url, method):
            token_headers = self._headers()
            if token_headers:
                request.headers.update(token_headers)
            elif caller_auth is not None:
                request.headers[caller_auth[0]] = caller_auth[1]
        return request

    def send(self, request: httpx.Request) -> httpx.Response:
        """Send a pre-built request through the guarded transport (one call)."""
        self._strip_credentials_unless_allowed(request)
        policy = self._retry
        last_exc: BaseException | None = None
        for attempt in range(1, policy.max_attempts + 1):
            if not self._budget.consume():
                raise ConnectorError("API call budget exhausted; partial results are truncated")
            try:
                response = self._http.send(request)
            except SafetyGuardError:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt >= policy.max_attempts or not policy.is_retryable_error(exc):
                    raise ConnectorError(f"request to {request.url} failed: {exc}") from exc
                policy.sleep(policy.delay_for(attempt, None))
                continue
            if policy.is_retryable_status(response.status_code) and attempt < policy.max_attempts:
                policy.sleep(policy.delay_for(attempt, response.headers.get("retry-after")))
                continue
            return response
        raise ConnectorError(f"request to {request.url} failed after retries: {last_exc}")

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        endpoint: str | None = None,
        experimental: bool = False,
    ) -> httpx.Response:
        """Send *method* + *path*; unverified endpoints need ``experimental``."""
        _check_experimental(endpoint or path, experimental=experimental)
        return self.send(self.build_request(method, path, params=params, headers=headers))

    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        endpoint: str | None = None,
        experimental: bool = False,
    ) -> httpx.Response:
        """GET helper funnelled through the guarded transport."""
        return self.request(
            "GET",
            path,
            params=params,
            headers=headers,
            endpoint=endpoint,
            experimental=experimental,
        )

    def head(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        endpoint: str | None = None,
        experimental: bool = False,
    ) -> httpx.Response:
        """HEAD helper funnelled through the guarded transport."""
        return self.request(
            "HEAD",
            path,
            params=params,
            headers=headers,
            endpoint=endpoint,
            experimental=experimental,
        )

    @contextmanager
    def stream(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        endpoint: str | None = None,
        experimental: bool = False,
    ) -> Iterator[httpx.Response]:
        """Streaming read funnelled through the guarded transport."""
        _check_experimental(endpoint or path, experimental=experimental)
        request = self.build_request(method, path, params=params, headers=headers)
        self._strip_credentials_unless_allowed(request)
        check_request(request, self._allowed_hosts)
        if not self._budget.consume():
            raise ConnectorError("API call budget exhausted; partial results are truncated")
        with self._http.stream(
            request.method, request.url, headers=request.headers, content=request.content
        ) as response:
            yield response

    @property
    def budget_used(self) -> int:
        """Calls consumed from this client's budget so far."""
        return self._budget.used

    @property
    def budget_remaining(self) -> int:
        """Calls left before this client's budget is exhausted."""
        return self._budget.remaining


__all__: list[str] = ["ENDPOINT_STATUS", "VERIFIED_ENDPOINTS", "ZohoClient"]
