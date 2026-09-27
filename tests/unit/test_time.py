"""Unit tests for time parsing (TK-CORE-5 scaffold)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from zohokit.core.time import InvalidTimeError, from_epoch_ms, parse, window


def test_parse_offset_and_z() -> None:
    assert parse("2026-09-27T12:00:00+05:30") == datetime(2026, 9, 27, 6, 30, tzinfo=UTC)
    assert parse("2026-09-27T06:30:00Z") == datetime(2026, 9, 27, 6, 30, tzinfo=UTC)


def test_parse_rejects_naive() -> None:
    with pytest.raises(InvalidTimeError):
        parse("2026-09-27T12:00:00")


def test_from_epoch_ms() -> None:
    assert from_epoch_ms(0) == datetime(1970, 1, 1, tzinfo=UTC)


def test_window_30d() -> None:
    now = datetime(2026, 9, 27, tzinfo=UTC)
    start, end = window("30d", now)
    assert end == now
    assert (end - start).days == 30


def test_window_rejects_bad_spec_and_naive_now() -> None:
    now = datetime(2026, 9, 27, tzinfo=UTC)
    with pytest.raises(InvalidTimeError):
        window("fortnight", now)
    with pytest.raises(InvalidTimeError):
        window("30d", datetime(2026, 9, 27))
