"""Pydantic input models for the migration preflight (legacy-v1 envelope)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class MigrationInput(BaseModel):
    """Offline source export: four entity lists plus the stage mapping."""

    model_config = ConfigDict(extra="allow")

    organizations: list[dict[str, Any]]
    people: list[dict[str, Any]]
    deals: list[dict[str, Any]]
    activities: list[dict[str, Any]]
    stage_mapping: dict[str, Any]


__all__: list[str] = ["MigrationInput"]
