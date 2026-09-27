"""Unit + property tests for money parsing (TK-CORE-4 scaffold)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from zohokit.core.money import (
    CurrencyError,
    MoneyError,
    RoundingPolicy,
    parse,
    quantize_money,
    validate_currency,
)


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


def test_quantize_policies() -> None:
    assert quantize_money(Decimal("2.665"), policy=RoundingPolicy.HALF_UP) == Decimal("2.67")
    assert quantize_money(Decimal("2.665"), policy=RoundingPolicy.HALF_EVEN) == Decimal("2.66")
    assert quantize_money(Decimal("10"), places=0) == Decimal("10")
    with pytest.raises(MoneyError):
        quantize_money(Decimal("1.00"), places=-1)


def test_validate_currency() -> None:
    assert validate_currency("usd") == "USD"
    assert validate_currency("INR") == "INR"
    with pytest.raises(CurrencyError):
        validate_currency("ZZZ")


@given(
    st.decimals(
        min_value=Decimal("-1000000"),
        max_value=Decimal("1000000"),
        allow_nan=False,
        allow_infinity=False,
    ),
    st.integers(min_value=0, max_value=4),
    st.sampled_from([RoundingPolicy.HALF_UP, RoundingPolicy.HALF_EVEN]),
)
def test_quantize_never_exceeds_places(
    amount: Decimal, places: int, policy: RoundingPolicy
) -> None:
    result = quantize_money(amount, places=places, policy=policy)
    assert -result.as_tuple().exponent <= places
