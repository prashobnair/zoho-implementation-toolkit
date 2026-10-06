"""Shared AI value objects: prompts, results, usage and config (STD §5).

Model names always come from configuration (environment or explicit
arguments) and are never hardcoded here. With no provider configured the
tool runs its deterministic path and reports ``AI disabled``.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from zohokit.core.ids import canonical_json

#: Status carried by every AI-assisted output (STD-AI3/4).
AiStatus = Literal["disabled", "ok", "repaired", "fallback"]


@dataclass(frozen=True)
class Prompt:
    """A fully rendered, redacted prompt ready for a provider (STD-AI2).

    ``text`` is the user message (source data already wrapped in
    delimited blocks); ``system`` carries the data-not-instructions
    statement. ``prompt_hash`` traces the exact bytes the provider saw.
    """

    feature: str
    version: str
    schema_name: str
    system: str
    text: str

    @property
    def prompt_hash(self) -> str:
        """SHA-256 over the canonical prompt bytes (traceability)."""
        payload = canonical_json(
            {
                "feature": self.feature,
                "version": self.version,
                "schema": self.schema_name,
                "system": self.system,
                "text": self.text,
            }
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AiUsage(BaseModel):
    """Token, cost and latency accounting for one AI call (STD-AI9)."""

    model_config = ConfigDict(frozen=True)

    provider: str = ""
    model: str = ""
    prompt_version: str = ""
    prompt_hash: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: int = 0
    status: AiStatus = "disabled"
    note: str = ""


class StructuredResult(BaseModel):
    """One provider call: raw text plus the parsed model (STD-AI1/3)."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    raw: str = ""
    data: Any = None
    usage: AiUsage = Field(default_factory=AiUsage)
    repaired: bool = False


@dataclass(frozen=True)
class AiConfig:
    """How to reach a provider. Built from config/env only, never literals.

    Environment: ``ZOHOKIT_AI_PROVIDER`` (``anthropic`` |
    ``openai-compatible`` | ``fake``), ``ZOHOKIT_AI_MODEL``,
    ``ZOHOKIT_AI_API_KEY`` (``ANTHROPIC_API_KEY`` is accepted for the
    Anthropic provider), ``ZOHOKIT_AI_BASE_URL`` (OpenAI-compatible
    endpoint), ``ZOHOKIT_AI_MAX_TOKENS``.
    """

    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    max_tokens: int = 2000
    has_api_key: bool = False

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AiConfig:
        """Read provider configuration from the environment."""
        source = env if env is not None else os.environ
        provider = source.get("ZOHOKIT_AI_PROVIDER")
        model = source.get("ZOHOKIT_AI_MODEL")
        base_url = source.get("ZOHOKIT_AI_BASE_URL")
        raw_budget = source.get("ZOHOKIT_AI_MAX_TOKENS", "").strip()
        budget = 2000
        if raw_budget:
            try:
                budget = int(raw_budget)
            except ValueError:
                budget = 2000
        has_key = bool(source.get("ZOHOKIT_AI_API_KEY", ""))
        if provider == "anthropic" and source.get("ANTHROPIC_API_KEY", ""):
            has_key = True
        return cls(
            provider=provider or None,
            model=model or None,
            base_url=base_url or None,
            max_tokens=budget,
            has_api_key=has_key,
        )

    @property
    def is_configured(self) -> bool:
        """True when a provider and model are named and keyed."""
        if self.provider == "fake":
            return self.model is not None
        if self.provider in ("anthropic", "openai-compatible"):
            return self.model is not None and self.api_key_present
        return False

    @property
    def api_key_present(self) -> bool:
        """Whether an API key exists (presence only, never the value)."""
        return self.has_api_key


__all__: list[str] = ["AiConfig", "AiStatus", "AiUsage", "Prompt", "StructuredResult"]
