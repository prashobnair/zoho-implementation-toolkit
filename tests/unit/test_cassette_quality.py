"""Cassette quality: timestamp-safe redaction, stable IDs, slim cassettes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from cassette_scan import scan_text  # noqa: E402

from zohokit.core.redact import (  # noqa: E402
    REDACTED_TOKEN,
    REDACTED_VALUE,
    Redactor,
    pseudonymise_org_id,
)

RECORD_ID = "1234567890123456789"
ORG_ID = "9876543210987654321"
CREATED = "2026-10-02T12:42:04+05:30"
TRIAL = "2026-10-17T05:30:00+05:30"


def _redactor() -> Redactor:
    return Redactor()


def test_timestamps_survive_intact() -> None:
    r = _redactor()
    assert r.redact_obj({"created_time": CREATED}) == {"created_time": CREATED}
    assert r.redact_obj({"Created_Time": CREATED}) == {"Created_Time": CREATED}
    assert r.redact_obj({"trial_expiry": TRIAL}) == {"trial_expiry": TRIAL}
    assert r.redact_obj({"Note": f"created {CREATED} done"}) == {"Note": f"created {CREATED} done"}
    assert scan_text(json.dumps({"created_time": CREATED}, indent=2), []) == []
    assert scan_text(json.dumps({"trial_expiry": TRIAL}, indent=2), []) == []


def test_record_ids_survive_but_identity_keys_masked() -> None:
    r = _redactor()
    assert r.redact_obj({"id": RECORD_ID}) == {"id": RECORD_ID}
    assert r.redact_obj({"record_id": RECORD_ID}) == {"record_id": RECORD_ID}
    assert r.redact_obj({"id": int(RECORD_ID)}) == {"id": int(RECORD_ID)}
    assert scan_text(json.dumps({"id": RECORD_ID}, indent=2), []) == []
    assert scan_text(json.dumps({"record_id": RECORD_ID}, indent=2), []) == []
    # Identity keys stay masked even for long numeric values.
    assert r.redact_obj({"zuid": RECORD_ID}) == {"zuid": REDACTED_VALUE}
    assert r.redact_obj({"zgid": RECORD_ID}) == {"zgid": REDACTED_VALUE}
    assert r.redact_obj({"primary_zuid": RECORD_ID}) == {"primary_zuid": REDACTED_VALUE}
    # Short numeric ids keep the old behaviour (still masked as phones).
    assert r.redact_obj({"id": "600012345"}) != {"id": "600012345"}


def test_org_id_pseudonymised_consistently() -> None:
    r = _redactor()
    first = r.redact_obj({"org": [{"id": ORG_ID}]})
    second = r.redact_obj({"org": [{"id": ORG_ID}]})
    expected = pseudonymise_org_id(ORG_ID)
    assert expected.startswith("org-")
    assert first == {"org": [{"id": expected}]}
    assert second == first
    # Same pseudonym across files/payloads (stable, deterministic).
    other = r.redact_obj({"org": [{"id": ORG_ID, "company_name": "Acme"}]})
    assert other["org"][0]["id"] == expected  # type: ignore[index]
    assert ORG_ID not in json.dumps(first)
    assert scan_text(json.dumps(first, indent=2), []) == []


def test_contact_pii_masked_but_country_stays() -> None:
    r = _redactor()
    org = r.redact_obj(
        {
            "org": [
                {
                    "id": ORG_ID,
                    "company_name": "Acme Widgets",
                    "Email": "owner@example.com",
                    "Phone": "+91 98200 11223",
                    "state": "Goa",
                    "city": "Panaji",
                    "country": "India",
                }
            ]
        }
    )
    entry = org["org"][0]
    assert entry["company_name"] == REDACTED_VALUE
    assert "@example.com" not in str(entry)
    assert "98200" not in str(entry)
    assert entry["state"] == REDACTED_VALUE
    assert entry["city"] == REDACTED_VALUE
    assert entry["country"] == "India"
    users = r.redact_obj(
        {
            "users": [
                {
                    "id": RECORD_ID,
                    "full_name": "Asha Menon",
                    "email": "asha@example.com",
                    "phone": "98765 43210",
                    "zuid": RECORD_ID,
                    "state": "Goa",
                    "city": "Panaji",
                    "country": "India",
                }
            ]
        }
    )
    user = users["users"][0]
    assert user["id"] == RECORD_ID
    assert user["full_name"] == REDACTED_VALUE
    assert user["zuid"] == REDACTED_VALUE
    assert user["state"] == REDACTED_VALUE
    assert user["city"] == REDACTED_VALUE
    assert user["country"] == "India"
    assert "asha@example.com" not in json.dumps(users)
    assert scan_text(json.dumps(org, indent=2), []) == []
    assert scan_text(json.dumps(users, indent=2), []) == []


def test_page_tokens_whole_redacted() -> None:
    r = _redactor()
    # Synthetic tokens are assembled from fragments (never one literal)
    # so the gitleaks security gate does not read the fixture as a leak.
    next_token = "90c6" + "abcdef0123456789fc09f0abcdef"
    prev_token = "1234" + "abcdef"
    payload = {
        "info": {
            "next_page_token": next_token,
            "previous_page_token": prev_token,
            "more_records": True,
        }
    }
    redacted = r.redact_obj(payload)
    assert redacted["info"]["next_page_token"] == REDACTED_TOKEN
    assert redacted["info"]["previous_page_token"] == REDACTED_TOKEN
    assert "90c6" not in json.dumps(redacted)
    assert scan_text(json.dumps(redacted, indent=2), []) == []


def _big_fields_payload() -> dict:
    fields: list[dict] = []
    for name in ("id", "Owner", "Created_Time", "Last_Name", "Deal_Name"):
        fields.append(
            {
                "api_name": name,
                "field_label": f"{name} label",
                "data_type": "string",
                "length": 100,
                "read_only": False,
                "system_mandatory": name == "id",
                "json_type": "string",
                "custom_secret": "drop-me",
                "lookup": {"module": {"api_name": "Accounts", "extra": 1}},
                "pick_list_values": [
                    {"actual_value": f"v{i:02d}", "display_value": f"V{i}"} for i in range(12)
                ],
            }
        )
    for i in range(30):
        fields.append(
            {
                "api_name": f"Custom_{i:02d}",
                "field_label": f"Custom {i}",
                "data_type": "string",
                "length": 50,
                "read_only": True,
                "system_mandatory": False,
                "json_type": "string",
                "internal_note": "drop-me",
            }
        )
    return {"fields": fields, "info": {"more_records": False}}


def test_slimmed_fields_deterministic() -> None:
    from record_cassette import slim_body

    payload = _big_fields_payload()
    once = slim_body(payload)
    twice = slim_body(json.loads(json.dumps(payload)))
    assert json.dumps(once, sort_keys=True) == json.dumps(twice, sort_keys=True)
    assert isinstance(once, dict) and isinstance(once["fields"], list)
    assert len(once["fields"]) <= 25
    names = [str(f.get("api_name")) for f in once["fields"]]
    assert names == sorted(names)
    for required in ("id", "Owner", "Created_Time", "Last_Name", "Deal_Name"):
        assert required in names
    for field in once["fields"]:
        assert isinstance(field, dict)
        assert set(field) <= {
            "api_name",
            "field_label",
            "data_type",
            "length",
            "read_only",
            "system_mandatory",
            "json_type",
            "lookup",
            "pick_list_values",
        }
        if "lookup" in field:
            assert field["lookup"] == {"module": {"api_name": "Accounts"}}
        if "pick_list_values" in field:
            assert len(field["pick_list_values"]) <= 10
            assert all(set(e) == {"actual_value"} for e in field["pick_list_values"])


def test_slimmed_modules_keep_only_committable_keys() -> None:
    from record_cassette import slim_body

    body = {
        "modules": [
            {
                "api_name": "Leads",
                "module_name": "Leads",
                "singular_label": "Lead",
                "plural_label": "Leads",
                "api_supported": True,
                "editable": True,
                "viewable": True,
                "generated_type": "default",
                "id": RECORD_ID,
                "internal_flag": "drop-me",
            }
        ]
    }
    slimmed = slim_body(body)
    assert isinstance(slimmed, dict)
    module = slimmed["modules"][0]  # type: ignore[index]
    assert set(module) == {
        "api_name",
        "module_name",
        "singular_label",
        "plural_label",
        "api_supported",
        "editable",
        "viewable",
        "generated_type",
        "id",
    }
    assert module["id"] == RECORD_ID


def test_scanner_allows_iso_and_id_keys_but_not_phones() -> None:
    assert scan_text(json.dumps({"Created_Time": CREATED}, indent=2), []) == []
    assert scan_text(json.dumps({"id": RECORD_ID}, indent=2), []) == []
    assert scan_text(json.dumps({"record_id": RECORD_ID}, indent=2), []) == []
    assert scan_text(json.dumps({"zuid": RECORD_ID}, indent=2), []) != []
    assert scan_text(json.dumps({"Phone": "+1 415-860-1234"}, indent=2), []) != []


def test_recorder_output_equals_scrub_and_scan_clean(monkeypatch, tmp_path: Path) -> None:
    """End to end: record -> scrub byte-identical -> scan clean."""
    import record_cassette
    import scrub_cassettes

    monkeypatch.setattr("zohokit.connectors.zoho.profiles.profiles_dir", lambda base=None: tmp_path)
    (tmp_path / "dev-in.json").write_text(
        '{"name": "dev-in", "dc": "in", '
        '"scopes": ["ZohoCRM.modules.READ", "ZohoCRM.settings.READ", '
        '"ZohoCRM.users.READ", "ZohoCRM.org.READ"], '
        '"environment": "developer_edition", "org_name": "", '
        '"saved_at": "2026-10-01T00:00:00+00:00"}',
        encoding="utf-8",
    )
    fields_body = _big_fields_payload()
    modules_body = {
        "modules": [
            {
                "api_name": "Leads",
                "module_name": "Leads",
                "singular_label": "Lead",
                "plural_label": "Leads",
                "api_supported": True,
                "editable": True,
                "viewable": True,
                "generated_type": "default",
                "id": RECORD_ID,
            }
        ]
    }
    org_body = {
        "org": [
            {
                "id": ORG_ID,
                "company_name": "Acme Widgets",
                "Email": "owner@example.com",
                "Phone": "+91 98200 11223",
                "state": "Goa",
                "city": "Panaji",
                "country": "India",
                "trial_expiry": TRIAL,
            }
        ]
    }
    users_body = {
        "users": [
            {
                "id": RECORD_ID,
                "full_name": "Asha Menon",
                "email": "asha@example.com",
                "phone": "98765 43210",
                "zuid": RECORD_ID,
                "state": "Goa",
                "city": "Panaji",
                "country": "India",
                "Created_Time": CREATED,
            }
        ],
        "info": {
            "per_page": 200,
            "count": 1,
            "page": 1,
            "more_records": True,
            "next_page_token": "90c6" + "abcdef0123456789fc09f0abcdef",
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/crm/v8/org":
            return httpx.Response(200, json=org_body)
        if path == "/crm/v8/users":
            return httpx.Response(200, json=users_body)
        if path == "/crm/v8/settings/fields":
            return httpx.Response(200, json=fields_body)
        if path == "/crm/v8/settings/modules":
            return httpx.Response(200, json=modules_body)
        return httpx.Response(404, json={"code": "NOT_FOUND"})

    cassettes_dir = tmp_path / "cassettes"
    jobs = (
        ("/crm/v8/org", "org.json"),
        ("/crm/v8/users", "users.json"),
        ("/crm/v8/settings/fields?module=Contacts", "fields_Contacts.json"),
        ("/crm/v8/settings/modules", "modules.json"),
    )
    for endpoint, filename in jobs:
        record_cassette.record(
            "crm",
            "dev-in",
            endpoint,
            cassettes_dir / "crm" / filename,
            allow_ci=True,
            token_provider=lambda: "fake-access-token",
            transport_factory=lambda: httpx.MockTransport(handler),
        )
    recorded = sorted((cassettes_dir / "crm").glob("*.json"))
    assert [p.name for p in recorded] == [
        "fields_Contacts.json",
        "modules.json",
        "org.json",
        "users.json",
    ]
    before = {p: p.read_bytes() for p in recorded}
    assert scrub_cassettes.main([str(cassettes_dir)]) == 0
    for path in recorded:
        assert path.read_bytes() == before[path], path.name
    for path in recorded:
        body = path.read_text(encoding="utf-8")
        document = json.loads(body)
        assert scan_text(body, []) == [], path.name
        # Timestamps and record IDs survive; identity/location PII does not.
        if path.name == "org.json":
            assert TRIAL in body
            assert ORG_ID not in body
            assert "Goa" not in body
            assert "owner@example.com" not in body
        if path.name == "users.json":
            assert CREATED in body
            assert RECORD_ID in body  # the user record id survives
            assert "asha@example.com" not in body
            assert "98765 43210" not in body
            assert "Asha Menon" not in body
            assert ("90c6" + "abcdef") not in body
            assert REDACTED_TOKEN in body
        if path.name == "fields_Contacts.json":
            slimmed = document["response"]["body"]
            assert len(slimmed["fields"]) <= 25
