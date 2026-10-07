"""Books live-pull tests over synthetic Books cassettes (TK-CONN-6).

Replays the contract cassettes through ``live_pull`` with a mock
transport and a stubbed token/profile — no network, no Zoho calls. One
malformed org response marks that org ``unavailable`` while the others
continue (TK-BK-F8). CRM Deals reads (UC-BK-1) replay synthetic
CRM v8 ``{"data", "info"}`` pages through ``live_pull_deals`` the same
way: explicit ``fields=`` list, period windowing, budget cap.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from zohokit.connectors.zoho.errors import ConnectorError
from zohokit.connectors.zoho.profiles import Profile, save_profile
from zohokit.modules.books.entities import load_entity_map
from zohokit.modules.books.live import (
    crm_deal_fields,
    live_pull,
    live_pull_deals,
    map_credit_note,
    map_deal,
    map_invoice,
)
from zohokit.modules.books.policy import CrmDealFields

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


# --- live CRM Deals (UC-BK-1) ----------------------------------------------------


def _crm_deals_handler(request: httpx.Request) -> httpx.Response:
    """Synthetic CRM v8 Deals pages (shaped like ``cassettes/crm/Deals.json``)."""
    assert request.url.path == "/crm/v8/Deals"
    page = request.url.params.get("page", "1")
    if page == "1":
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "555001001",
                        "Amount": 420000,
                        "Closing_Date": "2026-09-14",
                        "Currency": "INR",
                        "Account_Name": "Marigold Labs",
                        "Billing_Plan": "",
                        "Entity": "India",
                    },
                    {
                        "id": "555001002",
                        "Amount": 60000,
                        "Closing_Date": "2026-08-31",
                        "Currency": "INR",
                        "Account_Name": "Turmeric Trade",
                        "Billing_Plan": "",
                        "Entity": "India",
                    },
                    {
                        "id": "555001003",
                        "Amount": 26000,
                        "Closing_Date": "",
                        "Currency": "INR",
                        "Account_Name": "Orchid Goods",
                        "Billing_Plan": "",
                        "Entity": "India",
                    },
                ],
                "info": {"more_records": True, "count": 3, "page": 1, "per_page": 200},
            },
        )
    return httpx.Response(
        200,
        json={
            "data": [
                {
                    "id": "555001004",
                    "Amount": 10000,
                    "Closing_Date": "2026-09-15",
                    "Currency": "USD",
                    "Account_Name": "Marigold Labs US",
                    "Billing_Plan": "40/60",
                    "Entity": "US",
                }
            ],
            "info": {"more_records": False, "count": 1, "page": 2, "per_page": 200},
        },
    )


def _marigold_entities() -> dict[str, object]:
    root = Path(__file__).resolve().parent.parent.parent.parent
    return load_entity_map(root / "fixtures" / "books" / "marigold" / "entity_map.yaml")  # type: ignore[return-value]


def test_crm_deal_fields_are_explicit_for_v8(live_env: None) -> None:
    seen: dict[str, str] = {}

    def spy(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return _crm_deals_handler(request)

    fields = crm_deal_fields(CrmDealFields())
    assert "id" in fields
    for name in ("Amount", "Closing_Date", "Currency", "Account_Name", "Billing_Plan"):
        assert name in fields
    live_pull_deals(
        "dev-in",
        _marigold_entities(),
        CrmDealFields(),
        period_by="deal_closing_date",
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        transport_factory=lambda: httpx.MockTransport(spy),
    )
    sent = seen["fields"].split(",")
    assert "id" in sent
    for name in ("Amount", "Closing_Date", "Currency", "Account_Name"):
        assert name in sent


def test_live_pull_deals_maps_entities_and_windows_period(live_env: None) -> None:
    deals = live_pull_deals(
        "dev-in",
        _marigold_entities(),
        CrmDealFields(),
        period_by="deal_closing_date",
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        billing_plan_field="Billing_Plan",
        transport_factory=lambda: httpx.MockTransport(_crm_deals_handler),
    )
    by_id = {deal["id"]: deal for deal in deals}
    # 555001002 closed 2026-08-31: out of window, dropped here.
    assert set(by_id) == {"555001001", "555001003", "555001004"}
    assert by_id["555001001"]["entity"] == "in-entity"
    assert by_id["555001001"]["net_amount"] == "420000"
    assert by_id["555001001"]["customer_name"] == "Marigold Labs"
    assert by_id["555001001"]["currency"] == "INR"
    # Missing dates pass through so the engine flags invalid_date.
    assert by_id["555001003"]["closing_date"] == ""
    assert by_id["555001004"]["entity"] == "us-entity"
    assert by_id["555001004"]["Billing_Plan"] == "40/60"


def test_live_pull_deals_budget_caps_paging(live_env: None) -> None:
    with pytest.raises(ConnectorError, match="budget exhausted"):
        live_pull_deals(
            "dev-in",
            _marigold_entities(),
            CrmDealFields(),
            max_api_calls=1,
            transport_factory=lambda: httpx.MockTransport(_crm_deals_handler),
        )


def test_map_deal_shapes_offline_row() -> None:
    mapped = map_deal(
        "in-entity",
        {
            "id": "555001001",
            "Amount": 420000,
            "Closing_Date": "2026-09-14",
            "Currency": "INR",
            "Account_Name": "Marigold Labs",
            "Billing_Plan": "40/60",
            "Entity": "India",
        },
        CrmDealFields(),
        "Billing_Plan",
    )
    assert mapped["id"] == "555001001"
    assert mapped["entity"] == "in-entity"
    assert mapped["net_amount"] == "420000"
    assert mapped["closing_date"] == "2026-09-14"
    assert mapped["Billing_Plan"] == "40/60"
