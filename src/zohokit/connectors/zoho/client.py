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
from zohokit.connectors.zoho.guard import GetOnlyTransport
from zohokit.connectors.zoho.retry import RetryPolicy, default_timeouts

#: Endpoint call status (STD-C1/C2). Every endpoint in this release is
#: ``unverified``: hand-written from the official Zoho API docs with
#: synthetic cassettes, and therefore gated behind ``experimental=True``.
ENDPOINT_STATUS: dict[str, str] = {
    "/crm/v8/org": "unverified",
    "/crm/v8/settings/modules": "unverified",
    "/crm/v8/Leads": "unverified",
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

    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.BaseTransport | None = None,
        token_provider: Callable[[], str | None] | None = None,
        retry: RetryPolicy | None = None,
        budget: CallBudget | None = None,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            transport=GetOnlyTransport(transport or httpx.HTTPTransport()),
            timeout=default_timeouts(),
        )
        self._retry = retry or RetryPolicy()
        self._budget = budget or CallBudget(max_calls=DEFAULT_MAX_API_CALLS)
        self._token_provider = token_provider
        self.base_url = base_url.rstrip("/")

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
        merged = {**self._headers(), **(headers or {})}
        # httpx ships types, but build_request is typed loosely across
        # supported versions; pin the return so --strict stays exact.
        built = self._http.build_request(method, path, params=params, headers=merged)
        return cast(httpx.Request, built)  # type: ignore[redundant-cast]

    def send(self, request: httpx.Request) -> httpx.Response:
        """Send a pre-built request through the guarded transport (one call)."""
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


__all__: list[str] = ["ENDPOINT_STATUS", "ZohoClient"]
