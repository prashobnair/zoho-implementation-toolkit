"""RunContext tests (TK-ARCH-1): frozen clock in, never wall clock out."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from zohokit.core.context import RunContext


def test_naive_now_rejected() -> None:
    with pytest.raises(ValueError):
        RunContext(now=datetime(2026, 9, 27))


def test_frozen_context_roundtrip() -> None:
    now = datetime(2026, 9, 27, 12, tzinfo=UTC)
    ctx = RunContext(now=now)
    assert ctx.now == now
    assert ctx.mode == "offline"
