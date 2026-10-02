"""CLI: auth login/status, doctor and cache run offline against mocks."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from zohokit.cli import app
from zohokit.cli import auth as auth_cli
from zohokit.cli import doctor as doctor_cli

runner = CliRunner()


@pytest.fixture()
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    vault: dict[str, str] = {}

    def fake_set(service: str, key: str, value: str) -> None:
        vault[f"{service}:{key}"] = value

    def fake_get(service: str, key: str) -> str | None:
        return vault.get(f"{service}:{key}")

    monkeypatch.setattr("keyring.set_password", fake_set)
    monkeypatch.setattr("keyring.get_password", fake_get)
    return vault


def _token_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "refresh_token": "fake.refresh.token",
            "access_token": "fake.access.token",
            "api_domain": "https://www.zohoapis.in",
            "expires_in": 3600,
        },
    )


def _org_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"org": [{"id": "555000111", "company_name": "Marigold Labs"}]},
        headers={"date": "Thu, 01 Oct 2026 00:00:00 GMT"},
    )


def test_auth_login_reads_grant_from_stdin_not_argv(
    fake_keyring: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(auth_cli, "TRANSPORT_FACTORY", lambda: httpx.MockTransport(_token_handler))
    monkeypatch.setenv("ZOHO_CLIENT_ID", "kid")
    monkeypatch.setenv("ZOHO_CLIENT_SECRET", "ksecret")
    monkeypatch.setattr("zohokit.connectors.zoho.profiles.profiles_dir", lambda base=None: tmp_path)
    result = runner.invoke(
        app,
        ["auth", "login", "--profile", "dev-in", "--dc", "in", "--scopes", "ZohoCRM.modules.READ"],
        input="fake-grant-code\n",
    )
    assert result.exit_code == 0, result.output
    assert "Logged in profile 'dev-in'" in result.output
    assert fake_keyring["zohokit:dev-in:refresh_token"] == "fake.refresh.token"
    assert "fake.refresh.token" not in result.output


def test_auth_status_never_shows_tokens(
    fake_keyring: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_keyring["zohokit:dev-in:refresh_token"] = "fake.refresh.token"
    monkeypatch.setattr("zohokit.connectors.zoho.profiles.profiles_dir", lambda base=None: tmp_path)
    (tmp_path / "dev-in.json").write_text(
        '{"name": "dev-in", "dc": "in", "scopes": ["ZohoCRM.modules.READ"], '
        '"environment": "developer_edition", "org_name": "", '
        '"saved_at": "2026-10-01T00:00:00+00:00"}',
        encoding="utf-8",
    )
    result = runner.invoke(app, ["auth", "status", "--profile", "dev-in"])
    assert result.exit_code == 0, result.output
    assert "profile: dev-in" in result.output
    assert "dc: in" in result.output
    assert "ZohoCRM.modules.READ" in result.output
    assert "fake.refresh.token" not in result.output
    assert "ksecret" not in result.output


def test_doctor_cli_reports_checklist(
    fake_keyring: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_keyring["zohokit:dev-in:refresh_token"] = "fake.refresh.token"
    monkeypatch.setattr(doctor_cli, "TRANSPORT_FACTORY", lambda: httpx.MockTransport(_org_handler))
    monkeypatch.setattr(
        "zohokit.connectors.zoho.auth.TokenManager.ensure_fresh",
        lambda self: "fake-access-token",
    )
    monkeypatch.setattr("zohokit.connectors.zoho.profiles.profiles_dir", lambda base=None: tmp_path)
    (tmp_path / "dev-in.json").write_text(
        '{"name": "dev-in", "dc": "in", '
        '"scopes": ["ZohoCRM.modules.READ", "ZohoCRM.settings.READ", '
        '"ZohoCRM.users.READ", "ZohoCRM.org.READ"], '
        '"environment": "developer_edition", "org_name": "", '
        '"saved_at": "2026-10-01T00:00:00+00:00"}',
    )
    result = runner.invoke(app, ["doctor", "--live", "--profile", "dev-in", "--experimental"])
    assert result.exit_code == 0, result.output
    for name in (
        "dc_reachability",
        "token_refresh",
        "org_identity",
        "scope_sufficiency",
        "budget",
        "environment_type",
    ):
        assert name in result.output
    assert "555000111" not in result.output


def test_doctor_cli_redacts_check_details_before_printing() -> None:
    from zohokit.cli.doctor import redact_checks
    from zohokit.connectors.zoho.doctor import CheckResult, org_fingerprint

    fingerprinted = f"org {org_fingerprint('555000111')}"
    redacted = redact_checks(
        [
            CheckResult(
                "org_identity",
                "fail",
                "org read failed at /crm/v8/org (seen alice@example.com +14158601234)",
            ),
            CheckResult("org_identity", "pass", fingerprinted),
        ]
    )
    assert "alice@example.com" not in redacted[0].detail
    assert "+14158601234" not in redacted[0].detail
    assert "/crm/v8/org" in redacted[0].detail
    assert redacted[1].detail == fingerprinted


def test_doctor_cli_requires_live_and_profile() -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "--live" in result.output
    result = runner.invoke(app, ["doctor", "--live"])
    assert result.exit_code == 1
    assert "requires --profile" in result.output


def test_doctor_cli_over_privileged_scope_exits_3(
    fake_keyring: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_keyring["zohokit:dev-in:refresh_token"] = "fake.refresh.token"
    monkeypatch.setattr(doctor_cli, "TRANSPORT_FACTORY", lambda: httpx.MockTransport(_org_handler))
    monkeypatch.setattr(
        "zohokit.connectors.zoho.auth.TokenManager.ensure_fresh",
        lambda self: "fake-access-token",
    )
    monkeypatch.setattr("zohokit.connectors.zoho.profiles.profiles_dir", lambda base=None: tmp_path)
    (tmp_path / "dev-in.json").write_text(
        '{"name": "dev-in", "dc": "in", "scopes": ["ZohoCRM.modules.ALL"], '
        '"environment": "developer_edition", "org_name": "", '
        '"saved_at": "2026-10-01T00:00:00+00:00"}',
        encoding="utf-8",
    )
    result = runner.invoke(app, ["doctor", "--live", "--profile", "dev-in", "--experimental"])
    assert result.exit_code == 3
    assert "over_privileged_scope" in result.output


def test_cache_purge_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("zohokit.connectors.zoho.cache.cache_dir", lambda base=None: tmp_path)
    from zohokit.connectors.zoho.cache import ResponseCache

    ResponseCache(base=tmp_path).put("/crm/v8/org", None, {"id": "x"})
    result = runner.invoke(app, ["cache", "purge"])
    assert result.exit_code == 0
    assert "Purged 1 cached response(s)." in result.output
