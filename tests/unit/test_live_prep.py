"""Live preparation: nightly workflow lint, dev-in profile, evidence safety."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from cassette_scan import scan_all, scan_text  # noqa: E402

from zohokit.cli import app  # noqa: E402
from zohokit.cli import doctor as doctor_cli  # noqa: E402
from zohokit.connectors.zoho.budget import CallBudget  # noqa: E402
from zohokit.connectors.zoho.client import ZohoClient  # noqa: E402
from zohokit.connectors.zoho.doctor import (  # noqa: E402
    configured_modules,
    doctor_exit_code,
    run_doctor,
)
from zohokit.connectors.zoho.profiles import Profile  # noqa: E402
from zohokit.connectors.zoho.scopes import READ_SCOPES, find_over_privileged  # noqa: E402
from zohokit.core.redact import redact_text  # noqa: E402

runner = CliRunner()


def _live_workflow() -> dict[str, object]:
    text = (ROOT / ".github" / "workflows" / "live.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    assert isinstance(workflow, dict)
    return workflow


def _triggers(workflow: dict[str, object]) -> dict[str, object]:
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    return triggers


def _job(workflow: dict[str, object]) -> dict[str, object]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict) and len(jobs) == 1
    job = next(iter(jobs.values()))
    assert isinstance(job, dict)
    return job


def test_live_triggers_are_exactly_dispatch_plus_schedule() -> None:
    triggers = _triggers(_live_workflow())
    assert set(triggers) == {"workflow_dispatch", "schedule"}
    record = triggers["workflow_dispatch"]["inputs"]["record"]
    assert record["type"] == "boolean"
    assert record["default"] is False
    assert triggers["schedule"] != []


def test_live_job_guard_environment_and_permissions() -> None:
    job = _job(_live_workflow())
    guard = str(job.get("if", ""))
    assert "prashobnair/zoho-implementation-toolkit" in guard
    assert "refs/heads/main" in guard
    assert job["environment"] == "zoho-dev"
    assert job["permissions"] == {"contents": "read"}


def test_live_scan_runs_before_upload() -> None:
    steps = _job(_live_workflow())["steps"]
    assert isinstance(steps, list) and steps
    runs = [str(step.get("run", "")) for step in steps]
    uses = [str(step.get("uses", "")) for step in steps]
    scan_idx = next(i for i, run in enumerate(runs) if "cassette_scan.py" in run)
    scrub_idx = next(i for i, run in enumerate(runs) if "scrub_cassettes.py" in run)
    upload_idxs = [i for i, use in enumerate(uses) if "upload-artifact" in use]
    assert upload_idxs, "live job must upload evidence as an artifact"
    assert scrub_idx < scan_idx < min(upload_idxs)
    for step in steps:
        if "upload-artifact" in str(step.get("uses", "")):
            assert step["with"]["retention-days"] == 14
    # Evidence uploads only leave the runner when the fail-closed scan passed.
    for step in steps:
        if "upload-artifact" in str(step.get("uses", "")):
            condition = str(step.get("if", ""))
            assert "steps.scan.outcome == 'success'" in condition
            assert "always()" in condition
    # The scan itself stays fail-closed: no continue-on-error.
    scan_step = next(s for s in steps if "cassette_scan.py" in str(s.get("run", "")))
    assert scan_step.get("continue-on-error") is not True
    assert "always()" in str(scan_step.get("if", ""))
    # A final always() gate re-fails the run when doctor or smoke failed.
    gate = next(
        s for s in steps if "Fail the run when doctor or smoke failed" in str(s.get("name", ""))
    )
    assert "always()" in str(gate.get("if", ""))
    gate_run = str(gate.get("run", ""))
    assert "steps.doctor_json.outcome" in gate_run
    assert "steps.smoke.outcome" in gate_run


def test_live_doctor_and_smoke_do_not_stop_evidence_handling() -> None:
    steps = _job(_live_workflow())["steps"]
    assert isinstance(steps, list) and steps
    by_id = {str(s.get("id", "")): s for s in steps if s.get("id")}
    for step_id in ("doctor_json", "doctor_md", "smoke", "smoke_record", "scan"):
        assert step_id in by_id, f"live job must define step id {step_id!r}"
    # Doctor + smoke keep going so evidence is always scrubbed/scanned/uploaded.
    for step_id in ("doctor_json", "doctor_md", "smoke", "smoke_record"):
        assert by_id[step_id].get("continue-on-error") is True
    # Every step after the first doctor still runs its command once.
    for step_id in ("doctor_md", "smoke", "smoke_record"):
        assert "always()" in str(by_id[step_id].get("if", ""))
    assert "always()" in str(by_id["scan"].get("if", ""))
    scrub = next(s for s in steps if "scrub_cassettes.py" in str(s.get("run", "")))
    assert "always()" in str(scrub.get("if", ""))
    # The readable checklist is printed even when checks fail.
    showers = [
        s
        for s in steps
        if "evidence/doctor.md" in str(s.get("run", "")) and "cat" in str(s.get("run", ""))
    ]
    assert showers, "live job must cat evidence/doctor.md for the job log"
    assert all("always()" in str(s.get("if", "")) for s in showers)


def test_dev_in_profile_scopes_are_read_only() -> None:
    payload = json.loads((ROOT / "profiles" / "dev-in.json").read_text(encoding="utf-8"))
    profile = Profile.model_validate(payload)
    assert profile.name == "dev-in"
    assert profile.dc == "in"
    assert profile.environment == "developer_edition"
    assert sorted(profile.scopes) == sorted(READ_SCOPES["crm"])
    assert find_over_privileged(profile.scopes) == []


def test_crm_read_scopes_include_org() -> None:
    assert sorted(READ_SCOPES["crm"]) == [
        "ZohoCRM.modules.READ",
        "ZohoCRM.org.READ",
        "ZohoCRM.settings.READ",
        "ZohoCRM.users.READ",
    ]


def test_fingerprint_survives_redaction_and_scan() -> None:
    fingerprinted = "org sha256:1234567890123456"
    assert redact_text(fingerprinted) == fingerprinted
    assert scan_text(fingerprinted, []) == []


def test_scanner_still_catches_real_phone() -> None:
    findings = scan_text('{"Phone": "+1 415-860-1234"}', [])
    assert any("unredacted phone" in finding for finding in findings)


def test_scanner_passes_on_repo_tree() -> None:
    assert scan_all(ROOT) == {}


def test_scanner_and_scrub_bare_calls_ignore_process_argv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from cassette_scan import main as scan_main
    from scrub_cassettes import main as scrub_main

    monkeypatch.setattr(sys, "argv", ["pytest", "tests/unit/test_live_prep.py"])
    assert scan_main() == 0
    # Scrub stays off the repo tree: explicit-dir mode redacts only tmp files.
    cassette_dir = tmp_path / "cassettes"
    cassette_dir.mkdir()
    (cassette_dir / "crm.json").write_text(
        '{"Email": "someone@example.com", "id": "555000111"}', encoding="utf-8"
    )
    assert scrub_main([str(cassette_dir)]) == 0
    scrubbed = json.loads((cassette_dir / "crm.json").read_text(encoding="utf-8"))
    assert scrubbed["Email"] == "s***@example.invalid"


def _write_profile(tmp_path: Path) -> None:
    (tmp_path / "dev-in.json").write_text(
        '{"name": "dev-in", "dc": "in", '
        '"scopes": ["ZohoCRM.modules.READ", "ZohoCRM.settings.READ", '
        '"ZohoCRM.users.READ", "ZohoCRM.org.READ"], '
        '"environment": "developer_edition", "org_name": "", '
        '"saved_at": "2026-10-01T00:00:00+00:00"}',
        encoding="utf-8",
    )


def _org_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"org": [{"id": "555000111", "company_name": "Marigold Labs"}]},
        headers={"date": "Thu, 01 Oct 2026 00:00:00 GMT"},
    )


def test_doctor_json_and_markdown_evidence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    vault: dict[str, str] = {}
    monkeypatch.setattr("keyring.set_password", lambda s, k, v: vault.update({f"{s}:{k}": v}))
    monkeypatch.setattr("keyring.get_password", lambda s, k: vault.get(f"{s}:{k}"))
    vault["zohokit:dev-in:refresh_token"] = "fake.refresh.token"
    monkeypatch.setattr(doctor_cli, "TRANSPORT_FACTORY", lambda: httpx.MockTransport(_org_handler))
    monkeypatch.setattr(
        "zohokit.connectors.zoho.auth.TokenManager.ensure_fresh",
        lambda self: "fake-access-token",
    )
    monkeypatch.setattr("zohokit.connectors.zoho.profiles.profiles_dir", lambda base=None: tmp_path)
    _write_profile(tmp_path)
    json_out = tmp_path / "doctor.json"
    result = runner.invoke(
        app,
        [
            "doctor",
            "--live",
            "--profile",
            "dev-in",
            "--experimental",
            "--format",
            "json",
            "--out",
            str(json_out),
        ],
    )
    assert result.exit_code == 0, result.output
    document = json.loads(json_out.read_text(encoding="utf-8"))
    assert document["profile"] == "dev-in"
    assert sorted(document["scopes"]) == sorted(READ_SCOPES["crm"])
    assert [check["name"] for check in document["checks"]] == [
        "dc_reachability",
        "token_refresh",
        "org_identity",
        "clock_skew",
        "scope_sufficiency",
        "budget",
        "environment_type",
    ]
    assert all(check["status"] == "pass" for check in document["checks"])
    assert "555000111" not in json_out.read_text(encoding="utf-8")
    md_out = tmp_path / "doctor.md"
    result = runner.invoke(
        app,
        [
            "doctor",
            "--live",
            "--profile",
            "dev-in",
            "--experimental",
            "--format",
            "markdown",
            "--out",
            str(md_out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "555000111" not in md_out.read_text(encoding="utf-8")
    assert "org_identity" in md_out.read_text(encoding="utf-8")


def _smoke_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/crm/v8/org":
        return httpx.Response(
            200, json={"org": [{"id": "555000111", "company_name": "Marigold Labs"}]}
        )
    if path == "/crm/v8/settings/modules":
        return httpx.Response(
            200, json={"modules": [{"api_name": "Leads", "plural_label": "Leads"}]}
        )
    if path == "/crm/v8/settings/fields":
        return httpx.Response(200, json={"fields": [{"api_name": "Email", "data_type": "email"}]})
    if path == "/crm/v8/users":
        return httpx.Response(
            200,
            json={
                "users": [{"id": "555000002", "email": "o@example.invalid", "status": "active"}],
                "info": {"per_page": 200, "count": 1, "page": 1, "more_records": False},
            },
        )
    return httpx.Response(
        200,
        json={
            "data": [{"id": "555000001"}],
            "info": {"per_page": 5, "count": 1, "page": 1, "more_records": False},
        },
    )


def test_live_smoke_offline_writes_scannable_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import live_smoke

    monkeypatch.setattr(
        live_smoke, "TRANSPORT_FACTORY", lambda: httpx.MockTransport(_smoke_handler)
    )
    monkeypatch.setattr(live_smoke.TokenManager, "ensure_fresh", lambda self: "fake-access-token")
    monkeypatch.setattr("zohokit.connectors.zoho.profiles.profiles_dir", lambda base=None: tmp_path)
    _write_profile(tmp_path)
    evidence_dir = tmp_path / "evidence"
    code = live_smoke.main(
        ["--profile", "dev-in", "--evidence-dir", str(evidence_dir), "--max-api-calls", "200"]
    )
    assert code == 0
    text = (evidence_dir / "smoke.json").read_text(encoding="utf-8")
    document = json.loads(text)
    assert len(document["reads"]) == 9
    assert all(read["status"] == "pass" for read in document["reads"])
    assert "555000111" not in text
    assert "555000001" not in text
    assert scan_text(text, []) == []


def test_live_smoke_records_redacted_cassettes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import live_smoke

    monkeypatch.setattr(
        live_smoke, "TRANSPORT_FACTORY", lambda: httpx.MockTransport(_smoke_handler)
    )
    monkeypatch.setattr(live_smoke.TokenManager, "ensure_fresh", lambda self: "fake-access-token")
    monkeypatch.setattr("zohokit.connectors.zoho.profiles.profiles_dir", lambda base=None: tmp_path)
    _write_profile(tmp_path)
    cassettes_dir = tmp_path / "cassettes"
    code = live_smoke.main(
        [
            "--profile",
            "dev-in",
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--record",
            "--cassettes-dir",
            str(cassettes_dir),
        ]
    )
    assert code == 0
    recorded = sorted((cassettes_dir / "crm").glob("*.json"))
    assert len(recorded) == 9
    body = (cassettes_dir / "crm" / "org.json").read_text(encoding="utf-8")
    assert "555000111" not in body
    assert scan_text(body, []) == []


def test_live_smoke_contract_drift_exits_3(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import live_smoke

    def drift_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"wrong_shape": True})

    monkeypatch.setattr(live_smoke, "TRANSPORT_FACTORY", lambda: httpx.MockTransport(drift_handler))
    monkeypatch.setattr(live_smoke.TokenManager, "ensure_fresh", lambda self: "fake-access-token")
    monkeypatch.setattr("zohokit.connectors.zoho.profiles.profiles_dir", lambda base=None: tmp_path)
    _write_profile(tmp_path)
    code = live_smoke.main(["--profile", "dev-in", "--evidence-dir", str(tmp_path / "evidence")])
    assert code == 3


def test_live_smoke_tries_every_endpoint_despite_one_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One drift must not hide the others: every read is recorded, exit stays non-zero."""
    import live_smoke

    def partial_drift_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/crm/v8/org":
            return httpx.Response(200, json={"id": "555000111", "company_name": "Marigold Labs"})
        return _smoke_handler(request)

    monkeypatch.setattr(
        live_smoke, "TRANSPORT_FACTORY", lambda: httpx.MockTransport(partial_drift_handler)
    )
    monkeypatch.setattr(live_smoke.TokenManager, "ensure_fresh", lambda self: "fake-access-token")
    monkeypatch.setattr("zohokit.connectors.zoho.profiles.profiles_dir", lambda base=None: tmp_path)
    _write_profile(tmp_path)
    evidence_dir = tmp_path / "evidence"
    code = live_smoke.main(["--profile", "dev-in", "--evidence-dir", str(evidence_dir)])
    assert code == 3
    document = json.loads((evidence_dir / "smoke.json").read_text(encoding="utf-8"))
    assert len(document["reads"]) == 9
    # Note: smoke-read "name" values are structural checklist labels (a
    # "name" next to a "status" plus an "endpoint"), not people, so the
    # shared redactor leaves them alone; reads are still located by
    # endpoint here to stay independent of the label.
    org_reads = [read for read in document["reads"] if read["endpoint"] == "/crm/v8/org"]
    assert len(org_reads) == 1
    assert org_reads[0]["status"] == "fail"
    assert "/crm/v8/org" in org_reads[0]["error"]
    assert "555000111" not in org_reads[0]["error"]
    passing = [read for read in document["reads"] if read["status"] == "pass"]
    assert len(passing) == 8
    assert any(read["endpoint"] == "/crm/v8/settings/modules" for read in passing)
    assert any(read["endpoint"] == "/crm/v8/users" for read in passing)
    assert "555000111" not in json.dumps(document)


def _scope_client() -> ZohoClient:
    return ZohoClient("https://www.zohoapis.in", transport=httpx.MockTransport(_org_handler))


def _scope_profile(scopes: list[str]) -> Profile:
    return Profile.model_validate(
        {"name": "dev-in", "dc": "in", "scopes": scopes, "environment": "developer_edition"}
    )


def test_doctor_scope_ignores_unconfigured_books() -> None:
    assert configured_modules(sorted(READ_SCOPES["crm"])) == ["crm"]
    checks = run_doctor(
        _scope_profile(sorted(READ_SCOPES["crm"])),
        client_factory=_scope_client,
        token_refresher=lambda: True,
        budget=CallBudget(max_calls=200),
        experimental=True,
    )
    scope = next(c for c in checks if c.name == "scope_sufficiency")
    assert scope.status == "pass"
    assert "books" not in scope.detail.lower()
    assert doctor_exit_code(checks) == 0


def test_doctor_books_missing_is_warn_not_fail() -> None:
    scopes = [*sorted(READ_SCOPES["crm"]), "ZohoBooks.other.READ"]
    assert configured_modules(scopes) == ["crm", "books"]
    checks = run_doctor(
        _scope_profile(scopes),
        client_factory=_scope_client,
        token_refresher=lambda: True,
        budget=CallBudget(max_calls=200),
        experimental=True,
    )
    scope = next(c for c in checks if c.name == "scope_sufficiency")
    assert scope.status == "warn"
    assert "ZohoBooks.settings.READ" in scope.detail
    assert "for books" in scope.detail
    assert doctor_exit_code(checks) == 0


def test_doctor_crm_partial_missing_warns_with_module() -> None:
    scopes = ["ZohoCRM.modules.READ"]
    checks = run_doctor(
        _scope_profile(scopes),
        client_factory=_scope_client,
        token_refresher=lambda: True,
        budget=CallBudget(max_calls=200),
        experimental=True,
    )
    scope = next(c for c in checks if c.name == "scope_sufficiency")
    assert scope.status == "warn"
    assert "for crm" in scope.detail
    assert doctor_exit_code(checks) == 0


def test_doctor_json_out_also_prints_redacted_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    vault: dict[str, str] = {}
    monkeypatch.setattr("keyring.set_password", lambda s, k, v: vault.update({f"{s}:{k}": v}))
    monkeypatch.setattr("keyring.get_password", lambda s, k: vault.get(f"{s}:{k}"))
    vault["zohokit:dev-in:refresh_token"] = "fake.refresh.token"
    monkeypatch.setattr(doctor_cli, "TRANSPORT_FACTORY", lambda: httpx.MockTransport(_org_handler))
    monkeypatch.setattr(
        "zohokit.connectors.zoho.auth.TokenManager.ensure_fresh",
        lambda self: "fake-access-token",
    )
    monkeypatch.setattr("zohokit.connectors.zoho.profiles.profiles_dir", lambda base=None: tmp_path)
    _write_profile(tmp_path)
    json_out = tmp_path / "doctor.json"
    result = runner.invoke(
        app,
        [
            "doctor",
            "--live",
            "--profile",
            "dev-in",
            "--experimental",
            "--format",
            "json",
            "--out",
            str(json_out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json_out.exists()
    # The job log keeps the readable checklist even though the file got JSON.
    assert f"Wrote {json_out}" in result.output
    assert "scope_sufficiency" in result.output
    assert "[PASS]" in result.output
    assert "555000111" not in result.output
    assert "fake.refresh.token" not in result.output
