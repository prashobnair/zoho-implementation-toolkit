"""Pydantic input models for the timeline composer (legacy-v1 envelope)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class TimelineInput(BaseModel):
    """Account events with provenance, visibility and optional claims."""

    model_config = ConfigDict(extra="allow")

    events: list[dict[str, Any]]


__all__: list[str] = ["TimelineInput"]
