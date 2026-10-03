"""STD-X2: the cassette scanner fails on planted PII and passes clean trees."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import cassette_scan  # noqa: E402
from cassette_scan import main as scan_main  # noqa: E402
from cassette_scan import scan_all, scan_text  # noqa: E402


def test_planted_email_fails_scan(tmp_path: Path) -> None:
    cassette_dir = tmp_path / "cassettes"
    cassette_dir.mkdir()
    (cassette_dir / "crm.json").write_text(
        '{"Email": "someone.real@example.com", "id": "555000111"}', encoding="utf-8"
    )
    offenders = scan_all(tmp_path)
    assert "cassettes/crm.json" in offenders
    assert any("unredacted email" in finding for finding in offenders["cassettes/crm.json"])


def test_planted_phone_and_org_id_fail_scan() -> None:
    findings = scan_text('{"Phone": "+1 415-860-1234", "org": "600000999"}', ["600000999"])
    assert any("unredacted phone" in finding for finding in findings)
    assert any("configured org ID" in finding for finding in findings)


def test_planted_credential_fails_scan(tmp_path: Path) -> None:
    cassette_dir = tmp_path / "cassettes"
    cassette_dir.mkdir()
    (cassette_dir / "evil.json").write_text(
        '{"access_token": "1000.aa11bb22.cc33dd44", '
        '"note": "Bearer eyJhbGciOiJIUzI1NiJ9.e30.abc"},',
        encoding="utf-8",
    )
    offenders = scan_all(tmp_path)
    assert "cassettes/evil.json" in offenders
    assert any("credential" in finding for finding in offenders["cassettes/evil.json"])


def test_redacted_credentials_pass() -> None:
    findings = scan_text(
        '{"access_token": "[redacted-credential]", '
        '"note": "Zoho-oauthtoken [redacted-credential]"}',
        [],
    )
    assert findings == []


def test_recorder_drops_headers_and_refuses_accounts() -> None:
    from record_cassette import ALLOWED_HEADERS, filter_headers, refuse_accounts_host

    assert ALLOWED_HEADERS == frozenset({"content-type"})
    filtered = filter_headers(
        {"Authorization": "Zoho-oauthtoken tok", "Content-Type": "application/json"}
    )
    assert filtered == {"content-type": "application/json"}
    with pytest.raises(PermissionError, match="accounts host"):
        refuse_accounts_host("https://accounts.zoho.in/oauth/v2/token")
    refuse_accounts_host("https://www.zohoapis.in/crm/v8/org")


def test_redacted_placeholders_pass() -> None:
    findings = scan_text(
        '{"Email": "a***@example.invalid", "Phone": "+91********23", "id": "555000111"}', []
    )
    assert findings == []


def test_record_refuses_in_ci(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CI", "true")
    from record_cassette import record

    with pytest.raises(PermissionError, match="refusing to record in CI"):
        record("crm", "dev-in", "/crm/v8/org", tmp_path / "cassette-refused.json")


def test_scanner_passes_on_repo_tree() -> None:
    assert scan_main() == 0
    assert scan_all(ROOT) == {}


def test_scanner_output_never_contains_matched_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Scan-gate output is value-free: file, line, key and category only.

    Regression for the recording run whose scan failure printed the real
    phone into the public Actions log: every planted value (email, phone,
    token, org ID) must be absent from the scanner's stdout+stderr while
    every category is still reported.

    The planted secrets are assembled by concatenation (never a single
    ``name = "secret"`` literal) so the gitleaks security gate does not
    read the fixture itself as a leaked credential.
    """
    email = "pii.probe" + "@example.com"
    phone = "+49 170 " + "1234567"
    probe_oauth = "1000." + "abcdef12" + "." + "34567890"
    org_id = "6000" + "990011"
    cassette_dir = tmp_path / "cassettes"
    cassette_dir.mkdir()
    (cassette_dir / "crm.json").write_text(
        json.dumps(
            {
                "Contact_Email": email,
                "Contact_Phone": phone,
                "note": f"saw {probe_oauth} here",
                "company_id": org_id,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cassette_scan, "load_org_ids", lambda *_a, **_k: [org_id])
    assert scan_main([str(cassette_dir)]) == 1
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert email not in combined
    assert phone not in combined
    assert probe_oauth not in combined
    assert org_id not in combined
    assert "unredacted email" in combined
    assert "unredacted phone" in combined
    assert "unredacted credential" in combined
    assert "configured org ID" in combined
    # The JSON key is reported so the finding stays actionable without values.
    assert "Contact_Email" in combined
    assert "Contact_Phone" in combined


def test_structural_tz_offset_passes_scan() -> None:
    """In-range ``offset`` integers are time-zone data, not phone numbers."""
    assert scan_text('{"offset": 19800000}', []) == []
    assert scan_text('{"users": [{"offset": -18000000}]}', []) == []
    assert scan_text('{"offset": "19800000"}', []) == []


def test_out_of_range_offset_still_fails_scan() -> None:
    """98,765,432 ms exceeds +/-14 h, so it is scanned normally."""
    findings = scan_text('{"offset": "98765432"}', [])
    assert any("unredacted phone" in finding for finding in findings)


def test_offset_value_under_phone_key_still_fails_scan() -> None:
    findings = scan_text('{"phone": 19800000}', [])
    assert any("unredacted phone" in finding for finding in findings)


def test_benign_run_id_skips_phone_but_nothing_else() -> None:
    """Workflow-metadata IDs skip the phone rule by exact digit equality."""
    benign = ["71110022334"]
    assert scan_text("Run ID 71110022334 recorded", [], benign) == []
    assert any("unredacted phone" in f for f in scan_text("Run ID 71110022334 recorded", []))
    # Exact equality only: a longer run containing the ID still fails.
    assert any(
        "unredacted phone" in f for f in scan_text("Run ID 711100223345 recorded", [], benign)
    )
    # Other numbers on the same line still fail.
    assert any(
        "unredacted phone" in f for f in scan_text("Run ID 71110022334 call 4158601234", [], benign)
    )


def test_benign_ids_load_from_repo_file() -> None:
    from cassette_scan import load_benign_ids

    assert "37120123276" in load_benign_ids()
    assert load_benign_ids(ROOT / "does-not-exist.txt") == []


def test_record_then_scrub_is_byte_identical_and_scan_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Recorder == scrub: scrubbing a fresh recording changes NOTHING.

    Synthetic org + users + Leads payloads carry an 8-digit phone, a
    spaced mobile, emails, names, a ZUID and a street. They flow through
    the real recorder (redacted before write); re-running the scrub over
    the written cassettes must be byte-identical, and the scanner must
    pass over every file.
    """
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

    org_payload = {
        "org": [
            {
                "id": "600012345",
                "company_name": "Acme Widgets",
                "Phone": "23456789",
                "Email": "owner@example.com",
                "Mailing_Street": "12 Oracle Lane",
                "ZUID": "998877665544332211",
            }
        ]
    }
    users_payload = {
        "users": [
            {
                "id": "600012346",
                "name": "Asha Menon",
                "full_name": "Asha Menon",
                "first_name": "Asha",
                "last_name": "Menon",
                "email": "asha@example.com",
                "phone": "98765 43210",
                "zuid": "112233445566778899",
                "status": "active",
            }
        ],
        "info": {"per_page": 200, "count": 1, "page": 1, "more_records": False},
    }
    leads_payload = {
        "data": [
            {
                "id": "600012347",
                "Full_Name": "Ravi Kumar",
                "Last_Name": "Kumar",
                "Email": "ravi@example.com",
                "Phone": "23456789",
                "Mobile": "98765 43210",
                "Mailing_Street": "12 Oracle Lane",
            }
        ],
        "info": {"per_page": 5, "count": 1, "page": 1, "more_records": False},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/crm/v8/org":
            return httpx.Response(200, json=org_payload)
        if request.url.path == "/crm/v8/users":
            return httpx.Response(200, json=users_payload)
        if request.url.path == "/crm/v8/Leads":
            return httpx.Response(200, json=leads_payload)
        return httpx.Response(404, json={"code": "NOT_FOUND"})

    cassettes_dir = tmp_path / "cassettes"
    jobs = (
        ("/crm/v8/org", "org.json"),
        ("/crm/v8/users", "users.json"),
        ("/crm/v8/Leads", "Leads.json"),
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
    assert [path.name for path in recorded] == ["Leads.json", "org.json", "users.json"]
    before = {path: path.read_bytes() for path in recorded}
    assert scrub_cassettes.main([str(cassettes_dir)]) == 0
    for path in recorded:
        assert path.read_bytes() == before[path], path.name
    for path in recorded:
        body = path.read_text(encoding="utf-8")
        assert "23456789" not in body
        assert "98765 43210" not in body
        assert "owner@example.com" not in body
        assert "asha@example.com" not in body
        assert "ravi@example.com" not in body
        assert "Asha Menon" not in body
        assert "Ravi Kumar" not in body
        assert "998877665544332211" not in body
        assert "12 Oracle Lane" not in body
        assert scan_text(body, []) == []
