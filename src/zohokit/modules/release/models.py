"""Pydantic input models for release readiness (legacy-v1 envelope)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ReleaseInput(BaseModel):
    """Two config manifests: before and after."""

    model_config = ConfigDict(extra="allow")

    before: list[dict[str, Any]]
    after: list[dict[str, Any]]


__all__: list[str] = ["ReleaseInput"]
