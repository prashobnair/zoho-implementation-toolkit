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
        json={"id": "555000111", "company_name": "Marigold Labs"},
        headers={"date": "Thu, 01 Oct 2026 00:00:00 GMT"},
    )


def test_doctor_json_and_markdown_evidence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    vault: dict[str, str] = {}
    monkeypatch.setattr("keyring.set_password", lambda s, k, v: vault.update({f"{s}:{k}": v}))
    monkeypatch.setattr("keyring.get_password", lambda s, k: vault.get(f"{s}:{k}"))
    vault["zohokit:dev-in:refresh_token"] = "fake.refresh.token"
    monkeypatch.setattr(doctor_cli, "TRANSPORT_FACTORY", lambda: httpx.MockTransport(_org_handler))
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
        return httpx.Response(200, json={"id": "555000111", "company_name": "Marigold Labs"})
    if path == "/crm/v8/settings/modules":
        return httpx.Response(
            200, json={"modules": [{"api_name": "Leads", "plural_label": "Leads"}]}
        )
    if path == "/crm/v8/settings/fields":
        return httpx.Response(200, json={"fields": [{"api_name": "Email", "data_type": "email"}]})
    if path == "/crm/v8/users":
        return httpx.Response(
            200,
            json={"users": [{"id": "555000002", "email": "o@example.invalid", "status": "active"}]},
        )
    return httpx.Response(200, json={"data": [{"id": "555000001"}], "more_records": False})


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
