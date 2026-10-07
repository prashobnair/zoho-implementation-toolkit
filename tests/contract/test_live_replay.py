"""Contract replay over the verified live cassettes (offline, no network).

Replays the 9 redacted cassettes recorded by the owner-approved
verification run (see ``docs/evidence/2026-10-03/``) through the shared
readers. Runs under ``pytest -m contract --disable-socket``: every reply
comes from an ``httpx.MockTransport``, so no socket is ever opened.
Verified endpoints need no ``experimental`` flag (STD-C2); the docs
status column is tested against ``VERIFIED_ENDPOINTS`` below.
"""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path
from typing import Any

import httpx
import pytest

from zohokit.connectors.zoho.client import ENDPOINT_STATUS, VERIFIED_ENDPOINTS, ZohoClient
from zohokit.connectors.zoho.errors import ConnectorError
from zohokit.connectors.zoho.models import (
    FieldsResponse,
    ModulesResponse,
    RecordPage,
    UsersResponse,
    unwrap_fields,
    unwrap_modules,
    unwrap_users,
    validate_response,
)
from zohokit.connectors.zoho.readers import read_model, read_org, read_records

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parent.parent.parent
CASSETTES = ROOT / "cassettes" / "crm"
DOCS_TABLE = ROOT / "docs" / "API_CONTRACTS.md"

#: Cassette file per read name (the recorded redacted envelope).
CASSETTE_FILES = (
    "org.json",
    "modules.json",
    "fields_Leads.json",
    "fields_Contacts.json",
    "fields_Deals.json",
    "users.json",
    "Leads.json",
    "Contacts.json",
    "Deals.json",
)


def _body(name: str) -> dict[str, Any]:
    """Response body of the recorded envelope *name*."""
    envelope = json.loads((CASSETTES / name).read_text(encoding="utf-8"))
    body = envelope["response"]["body"]
    assert isinstance(body, dict)
    return body


def _verified_client() -> ZohoClient:
    """GET-only client replaying the 9 recorded bodies (no network)."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/crm/v8/org":
            return httpx.Response(200, json=_body("org.json"))
        if path == "/crm/v8/settings/modules":
            return httpx.Response(200, json=_body("modules.json"))
        if path == "/crm/v8/settings/fields":
            module = request.url.params.get("module", "")
            return httpx.Response(200, json=_body(f"fields_{module}.json"))
        if path == "/crm/v8/users":
            return httpx.Response(200, json=_body("users.json"))
        if path == "/crm/v8/Leads":
            return httpx.Response(200, json=_body("Leads.json"))
        if path == "/crm/v8/Contacts":
            return httpx.Response(200, json=_body("Contacts.json"))
        if path == "/crm/v8/Deals":
            return httpx.Response(200, json=_body("Deals.json"))
        return httpx.Response(404, json={"code": "NOT_FOUND"})

    return ZohoClient("https://www.zohoapis.in", transport=httpx.MockTransport(handler))


def test_all_nine_cassettes_present() -> None:
    assert sorted(path.name for path in CASSETTES.glob("*.json")) == sorted(CASSETTE_FILES)


def test_verified_org_replay_matches_evidence() -> None:
    read = read_org(_verified_client())
    assert read.org.id == "org-ce40ff0a"


def test_verified_modules_replay() -> None:
    validated = read_model(_verified_client(), "/crm/v8/settings/modules", ModulesResponse)
    modules = unwrap_modules(validated.model_dump(), endpoint="/crm/v8/settings/modules")
    assert len(modules) == 49
    names = {str(module.get("api_name")) for module in modules}
    assert {"Leads", "Contacts", "Deals"} <= names


def test_verified_users_replay() -> None:
    validated = read_model(_verified_client(), "/crm/v8/users", UsersResponse)
    users = unwrap_users(validated.model_dump(), endpoint="/crm/v8/users")
    assert len(users) == 1


@pytest.mark.parametrize("module", ["Leads", "Contacts", "Deals"])
def test_verified_fields_replay(module: str) -> None:
    validated = read_model(
        _verified_client(), "/crm/v8/settings/fields", FieldsResponse, params={"module": module}
    )
    fields = unwrap_fields(validated.model_dump(), endpoint="/crm/v8/settings/fields")
    assert len(fields) == 25
    names = {str(field.get("api_name")) for field in fields}
    assert {"id", "Created_Time"} <= names


@pytest.mark.parametrize("module", ["Leads", "Contacts", "Deals"])
def test_verified_record_pages_replay(module: str) -> None:
    page = read_records(_verified_client(), module)
    assert len(page.data) == 5
    assert page.more_records is True


def test_verified_record_pages_carry_info_envelope() -> None:
    page = validate_response(RecordPage, endpoint="/crm/v8/Leads", payload=_body("Leads.json"))
    assert page.info is not None
    assert page.info.more_records is True


def test_verified_reads_need_no_experimental_flag() -> None:
    """Every verified endpoint answers without ``experimental`` and stays silent."""
    client = _verified_client()
    targets: list[tuple[str, dict[str, str] | None]] = [
        (endpoint, None) for endpoint in sorted(VERIFIED_ENDPOINTS - {"/crm/v8/settings/fields"})
    ]
    targets.append(("/crm/v8/settings/fields", {"module": "Leads"}))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for endpoint, params in targets:
            response = client.get(endpoint, params=params, endpoint=endpoint)
            assert response.status_code == 200


def test_unverified_endpoints_still_require_experimental() -> None:
    client = _verified_client()
    with pytest.raises(ConnectorError, match="unverified"):
        client.get("/crm/v8/Accounts", endpoint="/crm/v8/Accounts")
    with pytest.warns(UserWarning, match="unverified"):
        response = client.get("/crm/v8/Accounts", endpoint="/crm/v8/Accounts", experimental=True)
    assert response.status_code == 404


def test_endpoint_status_derived_from_verified_set() -> None:
    assert set(ENDPOINT_STATUS) >= VERIFIED_ENDPOINTS
    for endpoint, status in ENDPOINT_STATUS.items():
        assert status == ("verified" if endpoint in VERIFIED_ENDPOINTS else "unverified")


def _docs_rows() -> list[tuple[str, str, str, str]]:
    """(endpoint, verified_on, verified_by, status) per docs table data row."""
    rows: list[tuple[str, str, str, str]] = []
    for line in DOCS_TABLE.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        # The fields row escapes its inner pipes (``Leads\|Contacts``),
        # so only unescaped pipes separate columns.
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line)]
        if cells[1] == "Product" or set(cells[1]) == {"-"}:
            continue
        endpoint = re.findall(r"`([^`]+)`", cells[2])[0]
        status = re.findall(r"`([^`]+)`", cells[10])[0]
        rows.append((endpoint, cells[8], cells[9], status))
    return rows


def test_docs_status_column_matches_verified_set() -> None:
    rows = _docs_rows()
    assert len(rows) == 24
    for endpoint, verified_on, verified_by, status in rows:
        expected = "verified" if endpoint in VERIFIED_ENDPOINTS else "unverified"
        assert status == expected, endpoint
        if expected == "verified":
            assert verified_on == "2026-10-03", endpoint
            assert "37120123276" in verified_by, endpoint
        else:
            assert verified_on == "—", endpoint


def test_docs_verified_set_covers_all_crm_reads() -> None:
    assert VERIFIED_ENDPOINTS == frozenset(
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
