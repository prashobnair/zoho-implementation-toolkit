"""Pydantic input models for books reconciliation (legacy-v1 envelope)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class BooksInput(BaseModel):
    """Two entities' deals plus the invoices claimed against them."""

    model_config = ConfigDict(extra="allow")

    entities: dict[str, Any]
    deals: list[dict[str, Any]]
    invoices: list[dict[str, Any]]


__all__: list[str] = ["BooksInput"]
