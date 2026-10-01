"""STD-W1/W2: signed plan bundles round-trip; tampering fails verification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from zohokit.cli import app
from zohokit.core.plan import (
    Plan,
    PlannedCall,
    PlanVerificationError,
    verify_bundle,
    write_bundle,
)

runner = CliRunner()

ROOT = Path(__file__).resolve().parent.parent.parent
RELEASE_FIXTURE = str(ROOT / "tests" / "golden" / "legacy" / "release" / "inputs" / "examples.json")


def _call() -> PlannedCall:
    return PlannedCall(
        method="POST",
        path="/crm/v8/Contacts",
        body_redacted={"email": "a***@example.invalid"},
        idempotency_key="csv:contacts:1",
        depends_on=[],
        rollback="Delete created contacts listed in the target-ID ledger.",
    )


def test_bundle_roundtrip_verifies(tmp_path: Path) -> None:
    json_path, md_path = write_bundle(Plan(calls=[_call()]), tmp_path)
    assert json_path.name == "plan.json"
    assert md_path.name == "plan.md"
    assert "SHA-256" in md_path.read_text(encoding="utf-8")
    assert verify_bundle(tmp_path) == Plan(calls=[_call()])


def test_tampered_plan_fails_verification(tmp_path: Path) -> None:
    write_bundle(Plan(calls=[_call()]), tmp_path)
    payload = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    payload["calls"][0]["path"] = "/crm/v8/Contacts/DELETE-EVERYTHING"
    (tmp_path / "plan.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PlanVerificationError, match="SHA-256 mismatch"):
        verify_bundle(tmp_path)


def test_missing_plan_fails_verification(tmp_path: Path) -> None:
    with pytest.raises(PlanVerificationError, match="missing"):
        verify_bundle(tmp_path)


def test_release_diff_plan_out_writes_signed_bundle(tmp_path: Path) -> None:
    plan_dir = tmp_path / "plan"
    result = runner.invoke(app, ["release", "diff", RELEASE_FIXTURE, "--plan-out", str(plan_dir)])
    assert result.exit_code == 0, result.output
    assert (plan_dir / "plan.json").exists()
    assert (plan_dir / "plan.md").exists()
    assert f"Wrote {plan_dir / 'plan.json'}" in result.output
    assert verify_bundle(plan_dir) == Plan()
