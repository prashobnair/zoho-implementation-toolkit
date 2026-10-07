"""Books live-pull tests over synthetic Books cassettes (TK-CONN-6).

Replays the contract cassettes through ``live_pull`` with a mock
transport and a stubbed token/profile — no network, no Zoho calls. One
malformed org response marks that org ``unavailable`` while the others
continue (TK-BK-F8).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from zohokit.connectors.zoho.profiles import Profile, save_profile
from zohokit.modules.books.live import live_pull, map_credit_note, map_invoice

ROOT = Path(__file__).resolve().parent.parent.parent.parent
CASSETTES = ROOT / "tests" / "contract" / "cassettes"


def _body(name: str) -> dict[str, object]:
    envelope = json.loads((CASSETTES / name).read_text(encoding="utf-8"))
    body = envelope["response"]["body"]
    assert isinstance(body, dict)
    return body


def _handler(request: httpx.Request) -> httpx.Response:
    params = request.url.params
    org = params.get("organization_id")
    if org == "555000009":
        return httpx.Response(200, json={"code": 101, "message": "bad org"})
    table = {
        ("/books/v3/invoices", "1"): _body("books_invoices_p1.json"),
        ("/books/v3/invoices", "2"): _body("books_invoices_p2.json"),
        ("/books/v3/contacts", "1"): _body("books_contacts.json"),
        ("/books/v3/creditnotes", "1"): _body("books_creditnotes.json"),
        ("/books/v3/settings/currencies", "1"): _body("books_currencies.json"),
        ("/books/v3/settings/taxes", "1"): _body("books_taxes.json"),
    }
    body = table.get((request.url.path, params.get("page", "1")))
    if body is None:
        return httpx.Response(404, json={"code": 1001, "message": "not found"})
    return httpx.Response(200, json=body)


@pytest.fixture()
def live_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("zohokit.connectors.zoho.profiles.profiles_dir", lambda base=None: tmp_path)
    save_profile(
        Profile(
            name="dev-in",
            dc="in",
            scopes=[
                "ZohoBooks.invoices.READ",
                "ZohoBooks.contacts.READ",
                "ZohoBooks.creditnotes.READ",
                "ZohoBooks.settings.READ",
            ],
            environment="developer_edition",
            books_orgs={"in-entity": "555000001", "bad-entity": "555000009"},
        ),
        base=tmp_path,
    )
    monkeypatch.setattr(
        "zohokit.connectors.zoho.auth.TokenManager.ensure_fresh", lambda self: "fake-token"
    )


def test_all_reads_hit_books_v3_paths(live_env: None) -> None:
    seen: list[str] = []

    def spy(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return _handler(request)

    bundles, _ = live_pull(
        "dev-in",
        {"in-entity": "555000001"},
        transport_factory=lambda: httpx.MockTransport(spy),
    )
    assert bundles["in-entity"]["invoices"]
    assert seen
    assert all(path.startswith("/books/v3/") for path in seen)


def test_map_invoice_shapes_offline_row() -> None:
    raw = _body("books_invoice_detail.json")["invoice"]
    assert isinstance(raw, dict)
    mapped = map_invoice("in-entity", raw)
    assert mapped["id"] == "555000201"
    assert mapped["entity"] == "in-entity"
    assert mapped["reference_number"] == "REF-001"
    assert mapped["custom_fields"] == [{"label": "CRM Deal ID", "value": "d-in-01"}]
    assert mapped["net_amount"] == "420000.0"


def test_map_credit_note_shapes_offline_row() -> None:
    raw = _body("books_creditnotes.json")["creditnotes"][0]
    assert isinstance(raw, dict)
    mapped = map_credit_note("in-entity", raw)
    assert mapped["id"] == "555000301"
    assert mapped["entity"] == "in-entity"


def test_live_pull_pages_and_isolates_bad_org(live_env: None) -> None:
    bundles, unavailable = live_pull(
        "dev-in",
        {"in-entity": "555000001", "bad-entity": "555000009"},
        transport_factory=lambda: httpx.MockTransport(_handler),
    )
    assert unavailable == ["bad-entity"]
    bundle = bundles["in-entity"]
    assert [item["id"] for item in bundle["invoices"]] == ["555000201", "555000202", "555000203"]
    assert [item["id"] for item in bundle["credit_notes"]] == ["555000301"]
    assert len(bundle["contacts"]) == 1
    assert len(bundle["currencies"]) == 2
    assert len(bundle["taxes"]) == 1
