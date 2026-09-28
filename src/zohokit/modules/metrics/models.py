"""Pydantic input models for metrics contracts (legacy-v1 envelope)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class MetricsInput(BaseModel):
    """CRM/Books/People tables plus freshness markers."""

    model_config = ConfigDict(extra="allow")

    as_of: Any
    currency: Any = None
    updated_at: Any = None
    accounts: list[dict[str, Any]]
    deals: list[dict[str, Any]]
    invoices: list[dict[str, Any]]
    staff: list[dict[str, Any]]


__all__: list[str] = ["MetricsInput"]
