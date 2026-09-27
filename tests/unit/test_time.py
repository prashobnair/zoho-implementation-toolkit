"""Unit tests for time parsing (TK-CORE-5 scaffold)."""

from __future__ import annotations

import calendar
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from zohokit.core.time import InvalidTimeError, from_epoch_ms, parse, window


def test_parse_offset_and_z() -> None:
    assert parse("2026-09-27T12:00:00+05:30") == datetime(2026, 9, 27, 6, 30, tzinfo=UTC)
    assert parse("2026-09-27T06:30:00Z") == datetime(2026, 9, 27, 6, 30, tzinfo=UTC)


def test_parse_rejects_naive() -> None:
    with pytest.raises(InvalidTimeError):
        parse("2026-09-27T12:00:00")


def test_from_epoch_ms() -> None:
    assert from_epoch_ms(0) == datetime(1970, 1, 1, tzinfo=UTC)


def test_from_epoch_ms_rejects_bool_and_non_int() -> None:
    for bad in (True, False, 1.5, "1000", None):
        with pytest.raises(InvalidTimeError):
            from_epoch_ms(bad)  # type: ignore[arg-type]


def test_from_epoch_ms_exact_negative() -> None:
    assert from_epoch_ms(-1000) == datetime(1969, 12, 31, 23, 59, 59, tzinfo=UTC)


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


@given(st.integers(min_value=0, max_value=2**41))
def test_epoch_ms_roundtrip(value: int) -> None:
    moment = from_epoch_ms(value)
    assert calendar.timegm(moment.utctimetuple()) == value // 1000
    assert moment.microsecond // 1000 == value % 1000
    assert parse(moment.isoformat()) == moment


@given(st.integers(min_value=1, max_value=365), st.sampled_from(["d", "h", "m"]))
def test_window_ends_at_now(amount: int, unit: str) -> None:
    now = datetime(2026, 9, 27, 12, tzinfo=UTC)
    start, end = window(f"{amount}{unit}", now)
    assert end == now
    assert start < end
