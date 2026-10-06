"""Suggestion schemas: the structured outputs every AI feature returns (STD-AI3).

These models are shared by the eval harness (``evals/<feature>/``) and the
CLI features. Every output parses into one of these schemas; on a parse
failure the pipeline gets one repair retry, then falls back to the
deterministic path with ``ai_status: "fallback"``. Nothing is ever
auto-applied: outputs are suggestions labeled ``source: "ai"``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExplainSentence(BaseModel):
    """One narrative sentence restating report findings (TK-CORE-9)."""

    model_config = ConfigDict(frozen=True)

    text: str = ""
    finding_ids: list[str] = Field(default_factory=list)
    quotes: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ExplainDraft(BaseModel):
    """Full narrative draft: one sentence per important point (TK-CORE-9)."""

    model_config = ConfigDict(frozen=True)

    sentences: list[ExplainSentence] = Field(default_factory=list)


class MappingSuggestion(BaseModel):
    """One source-column to target-field proposal (AI-MIG-1)."""

    model_config = ConfigDict(frozen=True)

    source_column: str = ""
    target_api_name: str | None = None
    # String form ("trim", "e164(region=IN)") or one-key mapping form
    # ({"map": {"values": {...}}}); both are accepted by coerce_transform.
    transform: list[Any] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""
    evidence_samples_idx: list[int] = Field(default_factory=list)


class MappingDraft(BaseModel):
    """Full mapping proposal: one entry per source column (AI-MIG-1)."""

    model_config = ConfigDict(frozen=True)

    suggestions: list[MappingSuggestion] = Field(default_factory=list)


class TransformDraft(BaseModel):
    """One value-transform proposal checked against samples (AI-MIG-2)."""

    model_config = ConfigDict(frozen=True)

    transform: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""
    evidence_samples_idx: list[int] = Field(default_factory=list)


__all__: list[str] = [
    "ExplainDraft",
    "ExplainSentence",
    "MappingDraft",
    "MappingSuggestion",
    "TransformDraft",
]
