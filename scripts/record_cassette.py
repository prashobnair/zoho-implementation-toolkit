"""Record a redacted cassette through the GET-only client (TK-CONN-9).

Usage: ``make record MODULE=<module> PROFILE=<profile> [PATH=/crm/v8/...]``

Reads flow through :class:`ZohoClient` (GET-only guard enforced), is
redacted with the shared :class:`Redactor` BEFORE anything is written,
and refuses to run in CI so cassettes can never be recorded where
secrets live. Request/response headers are dropped except for a small
allowlist, and the accounts token host is never recorded.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from zohokit.connectors.zoho.budget import CallBudget  # noqa: E402
from zohokit.connectors.zoho.cache import ResponseCache  # noqa: E402
from zohokit.connectors.zoho.client import ZohoClient  # noqa: E402
from zohokit.connectors.zoho.dc import DC_TABLE  # noqa: E402
from zohokit.connectors.zoho.profiles import load_profile  # noqa: E402
from zohokit.core.redact import Redactor, redact_text  # noqa: E402

#: Response/request headers kept in cassettes. Pagination rides in the
#: response body (``info.more_records``), so only the body media type
#: is needed to replay a cassette.
ALLOWED_HEADERS = frozenset({"content-type"})


def filter_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Keep only allowlisted headers, then redact their values."""
    redactor = Redactor()
    kept: dict[str, str] = {}
    for name, value in headers.items():
        if name.casefold() in ALLOWED_HEADERS:
            redacted_value = redactor.redact_obj(value)
            kept[name.casefold()] = (
                redacted_value if isinstance(redacted_value, str) else str(redacted_value)
            )
    return kept


def refuse_accounts_host(url: httpx.URL | str) -> None:
    """Raise unless *url* is not an accounts (token) host."""
    parsed = url if isinstance(url, httpx.URL) else httpx.URL(str(url))
    host = (parsed.host or "").casefold()
    if host.startswith("accounts.zoho") or host.startswith("accounts.zohocloud"):
        raise PermissionError(
            f"refusing to record accounts host {host!r}: cassettes never hold token traffic"
        )


def record(
    module: str,
    profile_name: str,
    path: str,
    out: Path,
    *,
    allow_ci: bool = False,
    token_provider: Callable[[], str | None] | None = None,
    budget: CallBudget | None = None,
    transport_factory: Callable[[], httpx.BaseTransport] | None = None,
) -> Path:
    """GET *path* through the guarded client and write the redacted cassette.

    Recording stays local-only unless *allow_ci* is set: the nightly live
    job passes it explicitly when the owner approves a ``record`` run, and
    every payload is still redacted before anything is written.
    """
    if os.environ.get("CI") and not allow_ci:
        raise PermissionError("refusing to record in CI: cassettes are recorded locally only")
    profile = load_profile(profile_name)
    api_base = DC_TABLE[profile.dc].api_base
    target = httpx.URL(path) if "://" in path else httpx.URL(api_base + path)
    refuse_accounts_host(target)
    transport = transport_factory() if transport_factory is not None else None
    client = ZohoClient(
        api_base, transport=transport, token_provider=token_provider, budget=budget or CallBudget()
    )
    response = client.get(path, endpoint=path.split("?")[0], experimental=True)
    refuse_accounts_host(response.request.url)
    # The full Redactor runs over the whole envelope BEFORE anything is
    # written — the same pass ``scrub_cassettes`` re-applies — so scrubbing
    # a freshly recorded cassette is a byte-identical no-op.
    cassette = Redactor().redact_obj(
        {
            "request": {
                "method": "GET",
                "url": str(target),
                "headers": filter_headers(response.request.headers),
            },
            "response": {
                "status": response.status_code,
                "headers": filter_headers(response.headers),
                "body": response.json(),
            },
        }
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cassette, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _ = (module, ResponseCache)
    return out


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``make record``."""
    parser = argparse.ArgumentParser(description="Record one redacted cassette.")
    parser.add_argument("--module", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        written = record(args.module, args.profile, args.path, Path(args.out))
    except (PermissionError, ValueError) as exc:
        # Value-free refusal: the error can echo the request URL, so it is
        # redacted before it reaches the log.
        print(f"record refused: {redact_text(str(exc))}", file=sys.stderr)
        return 1
    print(f"recorded {written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
