"""Run context: the engine never reads the wall clock directly (TK-ARCH-1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class RunContext:
    """Values an engine may need beyond its inputs.

    ``now`` is the run timestamp (callers pass a frozen clock in tests);
    ``mode`` mirrors the report envelope. AI provider and call budget
    arrive with later work packages.
    """

    now: datetime
    mode: Literal["offline", "live_read"] = "offline"

    def __post_init__(self) -> None:
        if self.now.tzinfo is None:
            raise ValueError("RunContext.now must be timezone-aware")


__all__: list[str] = ["RunContext"]
