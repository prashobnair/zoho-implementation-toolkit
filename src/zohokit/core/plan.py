"""Dry-run plan artifacts (STD-W1/W2): nothing ever writes to Zoho."""

from __future__ import annotations

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
