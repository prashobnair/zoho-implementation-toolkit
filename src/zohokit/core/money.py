"""Decimal-only money parsing (STD §2: never float)."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum

import pycountry

DEFAULT_MAX_DP = 2

_THOUSANDS_RE = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")
_NUMERIC_RE = re.compile(r"^[+-]?([0-9]*\.?[0-9]+|[0-9]+\.)$")
_NON_FINITE_RE = re.compile(r"^[+-]?(inf|infinity|nan)$", re.IGNORECASE)


class MoneyError(ValueError):
    """Raised when an amount breaks the parsing policy."""


class CurrencyError(ValueError):
    """Raised when a currency code is not an active ISO 4217 code."""


class RoundingPolicy(StrEnum):
    """Rounding policies for quantizing money (TK-CORE-4)."""

    HALF_UP = "half_up"
    HALF_EVEN = "half_even"


_ROUNDING_MODES = {
    RoundingPolicy.HALF_UP: ROUND_HALF_UP,
    RoundingPolicy.HALF_EVEN: ROUND_HALF_EVEN,
}


def quantize_money(
    amount: Decimal, *, places: int = 2, policy: RoundingPolicy = RoundingPolicy.HALF_UP
) -> Decimal:
    """Round ``amount`` to ``places`` decimal places under ``policy``."""
    if places < 0:
        raise MoneyError(f"places must be >= 0, got {places}")
    return amount.quantize(Decimal(1).scaleb(-places), rounding=_ROUNDING_MODES[policy])


def validate_currency(code: str) -> str:
    """Validate an ISO 4217 currency code; return it upper-cased."""
    normalized = code.strip().upper()
    if pycountry.currencies.get(alpha_3=normalized) is None:
        raise CurrencyError(f"unknown ISO 4217 currency code {code!r}")
    return normalized


def parse(
    value: str | int | Decimal,
    *,
    allow_negative: bool = False,
    max_dp: int = DEFAULT_MAX_DP,
) -> Decimal:
    """Parse an amount into ``Decimal``.

    Rules: no floats and no bools, ASCII digits only (no Unicode digits,
    no underscores), commas only as strict thousands grouping, no exponent
    notation, at most ``max_dp`` decimal places, finite, non-negative
    unless ``allow_negative`` is set. The result is never in exponent form
    and negative zero normalizes to zero.
    """
    if isinstance(value, float):
        raise MoneyError(f"float amounts are rejected, got {value!r}")
    if isinstance(value, bool):
        raise MoneyError(f"bool amounts are rejected, got {value!r}")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    else:
        text = value.strip()
        if "," in text:
            if _THOUSANDS_RE.match(text) is None:
                raise MoneyError(f"comma must be strict thousands grouping: {value!r}")
            text = text.replace(",", "")
        if "e" in text.casefold():
            raise MoneyError(f"exponent notation is rejected: {value!r}")
        if _NON_FINITE_RE.match(text) is not None:
            raise MoneyError(f"non-finite amount {value!r}")
        if _NUMERIC_RE.match(text) is None:
            raise MoneyError(f"invalid amount {value!r}")
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
    plain = Decimal(format(amount, "f"))
    return plain if not plain.is_zero() else abs(plain)
