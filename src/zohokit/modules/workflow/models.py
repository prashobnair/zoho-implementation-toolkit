"""Pydantic input models for the workflow simulator (legacy-v1 + v2 envelope)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorkflowInput(BaseModel):
    """One record, its rules, and the triggering event.

    ``initial_fields_changed`` / ``event_field`` describe the trigger
    itself (which fields the edit touched); v2 ``changed_to`` /
    ``changed_from`` criteria and ``field_changed(field)`` events read
    them. The legacy v1 path ignores both.
    """

    model_config = ConfigDict(extra="allow")

    rules: list[dict[str, Any]]
    record: dict[str, Any]
    initial_event: str = "deal_created"
    max_steps: int = Field(default=20, ge=1)
    initial_fields_changed: list[str] = Field(default_factory=list)
    event_field: str | None = None


__all__: list[str] = ["WorkflowInput"]
