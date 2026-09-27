"""Pydantic input models for forms parity (legacy-v1 envelope)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class FormsInput(BaseModel):
    """Source and target field lists plus the answer cases to compare."""

    model_config = ConfigDict(extra="allow")

    source_fields: list[dict[str, Any]]
    target_fields: list[dict[str, Any]]
    cases: list[dict[str, Any]]


__all__: list[str] = ["FormsInput"]
