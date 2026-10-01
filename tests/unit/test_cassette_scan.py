"""STD-X2: the cassette scanner fails on planted PII and passes clean trees."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

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
