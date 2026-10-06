"""Target-search replay over a synthetic v8 search cassette (TK-MIG-F5).

The record-search endpoint is `unverified` (see ``docs/API_CONTRACTS.md``):
live calls need ``--experimental``. This test replays a synthetic
cassette shaped like the real v8 envelope (``{"data": [...], "info":
{...}}``) through the shared GET-only client — no network — and proves
budget truncation reports ``checked 1 / 2``.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from zohokit.connectors.zoho.client import ZohoClient
from zohokit.connectors.zoho.errors import ConnectorError
from zohokit.modules.migration.live import SEARCH_PATH, live_search_fn
from zohokit.modules.migration.target_dedupe import (
    check_against_target,
    coverage_finding,
    target_fingerprint,
)

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parent.parent.parent
CASSETTE = ROOT / "tests" / "contract" / "cassettes" / "crm_search_contacts.json"

SEED_ID = "1455423000000476001"


def _cassette_body() -> dict[str, object]:
    return {
        "request": {
            "method": "GET",
            "url": "https://www.zohoapis.in/crm/v8/Contacts/search?criteria=(Email:equals:d@example.invalid)",
            "headers": {},
        },
        "response": {
            "body": {
                "data": [
                    {
                        "id": SEED_ID,
                        "Created_Time": "2026-10-02T12:42:04+05:30",
                        "Last_Name": "[redacted]",
                        "Email": "d***@example.invalid",
                    }
                ],
                "info": {"count": 1, "more_records": False, "page": 1, "per_page": 200},
            }
        },
    }


def test_search_cassette_shape_is_v8_envelope() -> None:
    body = json.loads(CASSETTE.read_text(encoding="utf-8"))["response"]["body"]
    assert sorted(body) == ["data", "info"]
    assert body["data"][0]["id"] == SEED_ID


def _search_client(seen: list[str]) -> ZohoClient:
    recorded = _cassette_body()["response"]
    assert isinstance(recorded, dict)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        assert request.url.path == "/crm/v8/Contacts/search"
        criteria = request.url.params.get("criteria", "")
        if "d@example.invalid" in criteria:
            return httpx.Response(200, json=recorded["body"])
        return httpx.Response(200, json={"data": [], "info": {"more_records": False}})

    return ZohoClient("https://www.zohoapis.in", transport=httpx.MockTransport(handler))


def test_search_needs_experimental_gate() -> None:
    client = _search_client([])
    with pytest.raises(ConnectorError):
        client.get(SEARCH_PATH.format(module="Contacts"), params={"criteria": "(Email:equals:x)"})


def test_search_replay_with_budget_truncation() -> None:
    seen: list[str] = []
    search = live_search_fn(_search_client(seen))
    candidates = [
        ("p-1", 2, "d@example.invalid", None),
        ("p-2", 3, "fresh@example.invalid", None),
    ]
    findings, checked, total, truncated = check_against_target(
        "people", "Contacts", candidates, search, budget=1
    )
    assert (checked, total, truncated) == (1, 2, True)
    assert [item.entity_id for item in findings] == ["p-1"]
    assert findings[0].evidence["target_fingerprint"] == target_fingerprint(SEED_ID)
    assert SEED_ID not in str(findings[0].evidence)
    assert any("criteria" in url for url in seen)
    coverage = coverage_finding("people", checked=checked, total=total, truncated=truncated)
    assert coverage.message == "Target duplicate search checked 1 / 2 rows."
