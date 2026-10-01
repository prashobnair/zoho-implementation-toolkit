"""GET-only guard at the httpx transport layer (STD-L1).

Every request the client sends flows through :class:`GetOnlyTransport`,
so ``request``, ``stream``, ``send`` and ``build_request`` + ``send`` are
all covered by construction. Anything that is not a plain GET or HEAD —
including disguised writes via method-override headers, ``_method`` query
parameters, or a body smuggled on a GET — raises :class:`SafetyGuardError`
before a single byte leaves the process.
"""

from __future__ import annotations

import httpx

from zohokit.connectors.zoho.errors import SafetyGuardError

_ALLOWED_METHODS = frozenset({"GET", "HEAD"})

_OVERRIDE_HEADERS = frozenset(
    {
        "x-http-method-override",
        "x-http-method",
        "x-method-override",
    }
)


def check_request(request: httpx.Request) -> None:
    """Raise :class:`SafetyGuardError` if *request* is not a plain read."""
    if request.method.upper() not in _ALLOWED_METHODS:
        raise SafetyGuardError(
            f"blocked {request.method} {request.url}: only GET and HEAD may leave this process"
        )
    for name in request.headers:
        if name.lower() in _OVERRIDE_HEADERS:
            raise SafetyGuardError(
                f"blocked disguised write on {request.url}: header {name!r} is never allowed"
            )
    if "_method" in request.url.params:
        raise SafetyGuardError(
            f"blocked disguised write on {request.url}: _method query parameter is never allowed"
        )
    if request.method.upper() == "GET" and len(request.content) > 0:
        raise SafetyGuardError(
            f"blocked GET with a request body on {request.url}: bodies never leave this process"
        )


class GetOnlyTransport(httpx.BaseTransport):
    """Sync transport wrapper enforcing the read-only guard."""

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self._inner = inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        check_request(request)
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


class AsyncGetOnlyTransport(httpx.AsyncBaseTransport):
    """Async transport wrapper enforcing the same read-only guard."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        check_request(request)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


__all__: list[str] = ["AsyncGetOnlyTransport", "GetOnlyTransport", "check_request"]
