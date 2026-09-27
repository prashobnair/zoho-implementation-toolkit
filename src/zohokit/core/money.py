"""Decimal-only money parsing (STD §2: never float)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

DEFAULT_MAX_DP = 2


class MoneyError(ValueError):
    """Raised when an amount breaks the parsing policy."""


def parse(
    value: str | int | Decimal,
    *,
    allow_negative: bool = False,
    max_dp: int = DEFAULT_MAX_DP,
) -> Decimal:
    """Parse an amount into ``Decimal``.

    Rules: no floats (they cannot represent money exactly), at most
    ``max_dp`` decimal places, finite, and non-negative unless
    ``allow_negative`` is set.
    """
    if isinstance(value, float):
        raise MoneyError(f"float amounts are rejected, got {value!r}")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    else:
        text = value.strip().replace(",", "")
        try:
            amount = Decimal(text)
        except InvalidOperation as exc:
            raise MoneyError(f"invalid amount {value!r}") from exc
    if not amount.is_finite():
        raise MoneyError(f"non-finite amount {value!r}")
    exponent = amount.as_tuple().exponent
    if not isinstance(exponent, int):  # unreachable after is_finite(); narrows the type
        raise MoneyError(f"non-finite amount {value!r}")
    if exponent < -max_dp:
        raise MoneyError(f"amount {value!r} exceeds {max_dp} decimal places")
    if amount < 0 and not allow_negative:
        raise MoneyError(f"negative amount {value!r} requires allow_negative=True")
    return amount
