"""Run context: the engine never reads the wall clock directly (TK-ARCH-1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal


@dataclass(frozen=True)
class RunContext:
    """Values an engine may need beyond its inputs.

    ``now`` is the run timestamp (callers pass a frozen clock in tests);
    ``mode`` mirrors the report envelope. ``ai_provider`` optionally holds
    an ``LLMProvider`` (typed as ``Any`` so ``core`` never imports
    ``zohokit.ai`` per the import-linter contract); ``ai_max_tokens`` caps
    estimated prompt tokens before the deterministic fallback runs.
    """

    now: datetime
    mode: Literal["offline", "live_read"] = "offline"
    ai_provider: Any = None
    ai_max_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.now.tzinfo is None:
            raise ValueError("RunContext.now must be timezone-aware")


__all__: list[str] = ["RunContext"]
