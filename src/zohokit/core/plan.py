"""Dry-run plan artifacts (STD-W1/W2): nothing ever writes to Zoho."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from zohokit.core.ids import canonical_json, fingerprint


class PlannedCall(BaseModel):
    """One intended API call, with rollback noted."""

    model_config = ConfigDict(frozen=True)

    method: str
    path: str
    body_redacted: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str
    depends_on: list[str] = Field(default_factory=list)
    rollback: str = ""


class Plan(BaseModel):
    """An ordered, hash-signed list of planned calls."""

    model_config = ConfigDict(frozen=True)

    calls: list[PlannedCall] = Field(default_factory=list)

    def canonical_hash(self) -> str:
        """SHA-256 over the canonical JSON so review can verify exactness."""
        payload = [call.model_dump(mode="json") for call in self.calls]
        return fingerprint([{"kind": "call", "name": canonical_json(item)} for item in payload])


class PlanVerificationError(ValueError):
    """A plan bundle failed verification: missing files or a hash mismatch."""


def write_bundle(plan: Plan, directory: Path, *, note: str = "") -> tuple[Path, Path]:
    """Write ``plan.json`` + ``plan.md`` into *directory* (STD-W1/W2).

    ``plan.json`` carries the calls plus the SHA-256 of their canonical
    JSON; ``plan.md`` is the human-readable companion. Returns both paths.
    """
    directory.mkdir(parents=True, exist_ok=True)
    digest = plan.canonical_hash()
    payload = {"sha256": digest, "calls": [call.model_dump(mode="json") for call in plan.calls]}
    json_path = directory / "plan.json"
    json_path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    lines = [
        "# Execution plan (read-only proposal)",
        "",
        f"SHA-256: `{digest}`",
        "",
        note or "This run proposes no writes to Zoho. Review every call before execution.",
        "",
        f"Planned calls: {len(plan.calls)}",
        "",
    ]
    for call in plan.calls:
        lines.append(f"- `{call.method} {call.path}` (idempotency `{call.idempotency_key}`)")
        if call.rollback:
            lines.append(f"  - rollback: {call.rollback}")
    md_path = directory / "plan.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def verify_bundle(directory: Path) -> Plan:
    """Re-read ``plan.json`` and raise unless its hash matches (STD-W2)."""
    import json

    json_path = directory / "plan.json"
    if not json_path.exists():
        raise PlanVerificationError(f"missing {json_path}")
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        plan = Plan.model_validate({"calls": payload.get("calls", [])})
    except ValueError as exc:
        raise PlanVerificationError(f"unreadable plan.json: {exc}") from exc
    if payload.get("sha256") != plan.canonical_hash():
        raise PlanVerificationError(
            "plan.json was modified after signing: SHA-256 mismatch "
            f"(signed {payload.get('sha256')!r}, recomputed {plan.canonical_hash()!r})"
        )
    return plan


__all__: list[str] = [
    "Plan",
    "PlanVerificationError",
    "PlannedCall",
    "verify_bundle",
    "write_bundle",
]
