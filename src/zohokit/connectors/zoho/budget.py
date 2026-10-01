"""Per-run API call budget (STD-L5)."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MAX_API_CALLS = 200


@dataclass
class CallBudget:
    """Counts outbound API calls; the run stops cleanly when exhausted."""

    max_calls: int = DEFAULT_MAX_API_CALLS
    used: int = 0

    def __post_init__(self) -> None:
        if self.max_calls < 1:
            raise ValueError("max_calls must be at least 1")

    @property
    def remaining(self) -> int:
        """Calls left before the budget is exhausted."""
        return max(self.max_calls - self.used, 0)

    @property
    def exhausted(self) -> bool:
        """True once no further calls may be made."""
        return self.used >= self.max_calls

    def consume(self, calls: int = 1) -> bool:
        """Record *calls* outbound calls; False when the budget is exhausted."""
        if self.exhausted:
            return False
        self.used += calls
        return True


__all__: list[str] = ["DEFAULT_MAX_API_CALLS", "CallBudget"]
