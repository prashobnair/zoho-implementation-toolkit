"""Pydantic input models for lead routing (legacy-v1 envelope)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class LeadRoutingInput(BaseModel):
    """Inbound leads to route, in received order."""

    model_config = ConfigDict(extra="allow")

    leads: list[dict[str, Any]]


__all__: list[str] = ["LeadRoutingInput"]
