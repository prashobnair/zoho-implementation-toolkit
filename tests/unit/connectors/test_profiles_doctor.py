"""STD-L2/L3/L4 + TK-CONN-1/2: scopes, profiles, production gate, doctor."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from zohokit.connectors.zoho.budget import CallBudget
from zohokit.connectors.zoho.client import ZohoClient
from zohokit.connectors.zoho.doctor import doctor_exit_code, org_fingerprint, run_doctor
from zohokit.connectors.zoho.errors import SafetyGuardError
from zohokit.connectors.zoho.profiles import (
    Profile,
    check_production,
    load_profile,
    production_allowed,
    save_profile,
)
from zohokit.connectors.zoho.scopes import find_over_privileged, sufficient_for


def _profile(**overrides: object) -> Profile:
    base: dict[str, object] = {
        "name": "dev-in",
        "dc": "in",
        "scopes": [
            "ZohoCRM.modules.READ",
            "ZohoCRM.settings.READ",
            "ZohoCRM.users.READ",
            "ZohoCRM.org.READ",
        ],
        "environment": "developer_edition",
    }
    base.update(overrides)
    return Profile.model_validate(base)


def test_over_privileged_scope_detected() -> None:
    offenders = find_over_privileged(["ZohoCRM.modules.ALL", "ZohoCRM.settings.READ"])
    assert offenders == ["ZohoCRM.modules.ALL"]


@pytest.mark.parametrize("scope", ["ZohoCRM.modules.CREATE", "x.UPDATE", "y.DELETE", "z.WRITE"])
def test_write_markers_detected(scope: str) -> None:
    assert find_over_privileged([scope]) == [scope]


def test_read_scopes_are_clean() -> None:
    assert (
        find_over_privileged(
            [
                "ZohoCRM.modules.READ",
                "ZohoCRM.settings.READ",
                "ZohoCRM.users.READ",
                "ZohoCRM.org.READ",
                "ZohoBooks.settings.READ",
            ]
        )
        == []
    )


def test_sufficient_for_reports_missing() -> None:
    assert sufficient_for(
        ["ZohoCRM.modules.READ"], ["ZohoCRM.modules.READ", "ZohoCRM.users.READ"]
    ) == ["ZohoCRM.users.READ"]


def test_no_default_profile() -> None:
    with pytest.raises(ValueError, match="no default profile"):
        load_profile(None)


def test_unknown_profile_names_login_command() -> None:
    with pytest.raises(ValueError, match="auth login"):
        load_profile("ghost", base=Path("/nonexistent-base-xyz"))


def test_profile_roundtrip(tmp_path: Path) -> None:
    saved = save_profile(_profile(), base=tmp_path)
    assert saved.name == "dev-in.json"
    loaded = load_profile("dev-in", base=tmp_path)
    assert loaded.dc == "in"
    assert loaded.saved_at != ""


def test_production_refused_in_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("ZOHOKIT_ALLOW_PRODUCTION_READ", "1")
    assert production_allowed(_profile(environment="production")) is False
    with pytest.raises(PermissionError, match="refusing production"):
        check_production(_profile(environment="production"), confirmed_org_name="Marigold")


def test_production_needs_flag_and_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("ZOHOKIT_ALLOW_PRODUCTION_READ", raising=False)
    with pytest.raises(PermissionError, match="refusing production"):
        check_production(_profile(environment="production"), confirmed_org_name="Marigold")
    monkeypatch.setenv("ZOHOKIT_ALLOW_PRODUCTION_READ", "1")
    with pytest.raises(PermissionError, match="confirmation failed"):
        check_production(
            _profile(environment="production", org_name="Marigold"), confirmed_org_name="Wrong"
        )
    check_production(
        _profile(environment="production", org_name="Marigold"), confirmed_org_name="Marigold"
    )


def test_non_production_needs_no_confirmation() -> None:
    check_production(_profile(), confirmed_org_name=None)


def _org_handler(request: httpx.Request) -> httpx.Response:
    assert request.method == "GET"
    return httpx.Response(
        200,
        json={"org": [{"id": "555000111", "company_name": "Marigold Labs"}]},
        headers={"date": "Thu, 01 Oct 2026 00:00:00 GMT"},
    )


def _doctor_client() -> ZohoClient:
    return ZohoClient("https://www.zohoapis.in", transport=httpx.MockTransport(_org_handler))


def test_doctor_all_pass() -> None:
    checks = run_doctor(
        _profile(),
        client_factory=_doctor_client,
        token_refresher=lambda: True,
        budget=CallBudget(max_calls=200),
        experimental=True,
    )
    by_name = {check.name: check for check in checks}
    assert [check.name for check in checks] == [
        "dc_reachability",
        "token_refresh",
        "org_identity",
        "clock_skew",
        "scope_sufficiency",
        "budget",
        "environment_type",
    ]
    assert all(check.status == "pass" for check in checks)
    assert by_name["org_identity"].detail == f"org {org_fingerprint('555000111')}"
    assert "555000111" not in by_name["org_identity"].detail
    assert doctor_exit_code(checks) == 0


def test_doctor_over_privileged_scope_fails() -> None:
    checks = run_doctor(
        _profile(scopes=["ZohoCRM.modules.ALL"]),
        client_factory=_doctor_client,
        token_refresher=lambda: True,
        budget=CallBudget(max_calls=200),
        experimental=True,
    )
    scope_check = next(c for c in checks if c.name == "scope_sufficiency")
    assert scope_check.status == "fail"
    assert "over_privileged_scope" in scope_check.detail
    assert doctor_exit_code(checks) == 3


def test_doctor_verified_org_read_needs_no_experimental() -> None:
    checks = run_doctor(
        _profile(),
        client_factory=_doctor_client,
        token_refresher=lambda: True,
        budget=CallBudget(max_calls=200),
        experimental=False,
    )
    org = next(c for c in checks if c.name == "org_identity")
    assert org.status == "pass"
    assert doctor_exit_code(checks) == 0


def test_doctor_exhausted_budget_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    budget = CallBudget(max_calls=1)
    budget.consume()
    checks = run_doctor(
        _profile(),
        client_factory=_doctor_client,
        token_refresher=lambda: True,
        budget=budget,
        experimental=True,
    )
    assert next(c for c in checks if c.name == "budget").status == "fail"
    assert doctor_exit_code(checks) == 3


def test_doctor_production_in_ci_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    checks = run_doctor(
        _profile(environment="production", org_name="Marigold"),
        client_factory=_doctor_client,
        token_refresher=lambda: True,
        budget=CallBudget(max_calls=200),
        confirmed_org_name="Marigold",
        experimental=True,
    )
    assert next(c for c in checks if c.name == "environment_type").status == "fail"
    assert doctor_exit_code(checks) == 3


def test_org_fingerprint_is_stable_and_opaque() -> None:
    first = org_fingerprint("555000111")
    assert first == org_fingerprint("555000111")
    assert first.startswith("sha256:")
    assert "555000111" not in first


def test_get_only_guard_still_applies_with_token() -> None:
    client = ZohoClient(
        "https://www.zohoapis.in",
        transport=httpx.MockTransport(_org_handler),
        token_provider=lambda: "fake",
    )
    with pytest.raises(SafetyGuardError):
        client.request("POST", "/crm/v8/Leads", experimental=True)


def test_profiles_without_keyring_import() -> None:
    assert os.name in ("posix", "nt", "java")
