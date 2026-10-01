"""GET-only guard at the httpx transport layer (STD-L1).

Every request the client sends flows through :class:`GetOnlyTransport`,
so ``request``, ``stream``, ``send`` and ``build_request`` + ``send`` are
all covered by construction. Anything that is not a plain GET or HEAD —
including disguised writes via method-override headers, ``_method`` query
parameters, or a body smuggled on a GET — raises :class:`SafetyGuardError`
before a single byte leaves the process.

The guard also pins the request target (STD-L1 credential-confinement):
only ``https`` URLs on an explicit allowlist of Zoho API hosts with the
default port reach the network. Anything else — another host, an
``http`` downgrade, a non-default port, ``userinfo@host`` or an IP
literal — raises :class:`SafetyGuardError` before send, and the client
never attaches the ``Authorization`` header to such a request.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable

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

#: Host suffixes trusted for API calls. ``api_domain`` values from the
#: token response must land under one of these (``*.zohoapis.<tld>`` or
#: ``*.zoho.<tld>``); anything else is never allowlisted.
TRUSTED_API_SUFFIXES = frozenset(
    {
        "zohoapis.com",
        "zohoapis.eu",
        "zohoapis.in",
        "zohoapis.com.au",
        "zohoapis.jp",
        "zohoapis.ca",
        "zohoapis.com.cn",
        "zoho.com",
        "zoho.eu",
        "zoho.in",
        "zoho.com.au",
        "zoho.jp",
        "zoho.ca",
        "zoho.com.cn",
    }
)

_HOST_LABEL_RE = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*$")


def is_trusted_api_host(host: str) -> bool:
    """True when *host* is a ``*.zohoapis.<tld>`` / ``*.zoho.<tld>`` name."""
    lowered = host.casefold().rstrip(".")
    if not lowered or "@" in lowered or ":" in lowered or " " in lowered:
        return False
    if lowered.startswith("accounts."):
        # Token hosts never carry API calls; auth uses AuthTransport only.
        return False
    if not _HOST_LABEL_RE.match(lowered):
        return False
    try:
        ipaddress.ip_address(lowered)
    except ValueError:
        pass
    else:
        return False
    return any(
        lowered != suffix and lowered.endswith("." + suffix) for suffix in TRUSTED_API_SUFFIXES
    )


def api_host_from_url(url_value: str) -> str:
    """Extract and validate the API host from an ``api_domain`` URL or host."""
    candidate = url_value.strip()
    if "://" in candidate:
        host = httpx.URL(candidate).host
    else:
        host = httpx.URL(f"https://{candidate}").host
    if not host or not is_trusted_api_host(host):
        raise SafetyGuardError(
            f"refusing untrusted api_domain {url_value!r}: "
            "must match *.zohoapis.<tld> or *.zoho.<tld>"
        )
    return host.casefold()


def _has_body(request: httpx.Request) -> bool:
    """True when *request* carries a body, without consuming a stream."""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length.strip()) > 0:
                return True
        except ValueError:
            return True
    if "transfer-encoding" in request.headers:
        return True
    try:
        content = request.content
    except httpx.RequestNotRead:
        # A streaming body is still a body: block without reading it.
        return True
    except Exception:
        # Fail closed: an unreadable body never leaves the process.
        return True
    return len(content) > 0


def check_url_allowed(url: httpx.URL, allowed_hosts: Iterable[str] | None) -> str:
    """Raise :class:`SafetyGuardError` unless *url* may carry credentials."""
    if url.scheme != "https":
        raise SafetyGuardError(f"blocked {url}: only https URLs may leave this process")
    try:
        has_userinfo = bool(url.username) or bool(url.password)
    except Exception:
        has_userinfo = True
    if has_userinfo:
        raise SafetyGuardError(f"blocked {url}: userinfo in URLs is never allowed")
    host = url.host or ""
    if not host:
        raise SafetyGuardError(f"blocked {url}: missing host")
    lowered = host.casefold()
    try:
        ipaddress.ip_address(lowered.rstrip("."))
    except ValueError:
        pass
    else:
        raise SafetyGuardError(f"blocked {url}: IP literals never carry credentials")
    if url.port is not None:
        raise SafetyGuardError(f"blocked {url}: only the default https port may leave this process")
    if not is_trusted_api_host(host):
        raise SafetyGuardError(f"blocked {url}: host is not a trusted Zoho API domain")
    if allowed_hosts is not None and lowered.rstrip(".") not in {
        entry.casefold().rstrip(".") for entry in allowed_hosts
    }:
        raise SafetyGuardError(f"blocked {url}: host is not in this client's API allowlist")
    return lowered


def check_request(request: httpx.Request, allowed_hosts: Iterable[str] | None = None) -> None:
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
    for key in request.url.params:
        if key.casefold() == "_method":
            raise SafetyGuardError(
                f"blocked disguised write on {request.url}: "
                "_method query parameter is never allowed"
            )
    check_url_allowed(request.url, allowed_hosts)
    if request.method.upper() in ("GET", "HEAD") and _has_body(request):
        raise SafetyGuardError(
            f"blocked {request.method} with a request body on {request.url}: "
            "bodies never leave this process"
        )


class GetOnlyTransport(httpx.BaseTransport):
    """Sync transport wrapper enforcing the read-only guard."""

    def __init__(self, inner: httpx.BaseTransport, allowed_hosts: set[str] | None = None) -> None:
        self._inner = inner
        self._allowed_hosts = allowed_hosts

    def add_allowed_host(self, host: str) -> str:
        """Allowlist *host* after trusting it; returns the normalized host."""
        if self._allowed_hosts is None:
            self._allowed_hosts = set()
        normalized = api_host_from_url(host)
        self._allowed_hosts.add(normalized)
        return normalized

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        check_request(request, self._allowed_hosts)
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


class AsyncGetOnlyTransport(httpx.AsyncBaseTransport):
    """Async transport wrapper enforcing the same read-only guard."""

    def __init__(
        self, inner: httpx.AsyncBaseTransport, allowed_hosts: set[str] | None = None
    ) -> None:
        self._inner = inner
        self._allowed_hosts = allowed_hosts

    def add_allowed_host(self, host: str) -> str:
        """Allowlist *host* after trusting it; returns the normalized host."""
        if self._allowed_hosts is None:
            self._allowed_hosts = set()
        normalized = api_host_from_url(host)
        self._allowed_hosts.add(normalized)
        return normalized

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        check_request(request, self._allowed_hosts)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


__all__: list[str] = [
    "TRUSTED_API_SUFFIXES",
    "AsyncGetOnlyTransport",
    "GetOnlyTransport",
    "api_host_from_url",
    "check_request",
    "check_url_allowed",
    "is_trusted_api_host",
]
