"""Unit + property tests for money parsing (TK-CORE-4 scaffold)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from zohokit.core.money import MoneyError, parse


def test_parse_valid_amounts() -> None:
    assert parse("4.20") == Decimal("4.20")
    assert parse("1,234.50") == Decimal("1234.50")
    assert parse(7) == Decimal(7)
    assert parse(Decimal("0.01")) == Decimal("0.01")


def test_parse_rejects_float() -> None:
    with pytest.raises(MoneyError):
        parse(4.2)  # type: ignore[arg-type]


def test_parse_rejects_too_many_places() -> None:
    with pytest.raises(MoneyError):
        parse("1.234")


def test_parse_rejects_negative_by_default() -> None:
    with pytest.raises(MoneyError):
        parse("-5.00")
    assert parse("-5.00", allow_negative=True) == Decimal("-5.00")


def test_parse_rejects_garbage() -> None:
    with pytest.raises(MoneyError):
        parse("not-money")


@given(st.integers(min_value=0, max_value=10_000_000))
def test_parse_paise_roundtrip(paise: int) -> None:
    amount = Decimal(paise) / Decimal(100)
    assert parse(format(amount, "f")) == amount


@given(st.lists(st.integers(min_value=0, max_value=100_000), max_size=10))
def test_sum_of_parsed_never_touches_float(paise_values: list[int]) -> None:
    total = sum((parse(p) / Decimal(100) for p in paise_values), Decimal(0))
    assert total == sum((Decimal(p) / Decimal(100) for p in paise_values), Decimal(0))
