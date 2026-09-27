"""Pydantic input models for the workflow simulator (legacy-v1 envelope)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorkflowInput(BaseModel):
    """One record, its rules, and the triggering event."""

    model_config = ConfigDict(extra="allow")

    rules: list[dict[str, Any]]
    record: dict[str, Any]
    initial_event: str = "deal_created"
    max_steps: int = Field(default=20, ge=1)


__all__: list[str] = ["WorkflowInput"]
