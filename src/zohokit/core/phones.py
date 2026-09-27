"""E.164 phone normalization with explicit regions (STD §2).

Region inference only happens via an explicit ``default_region`` argument,
and such numbers carry the ``inferred_region`` flag. There is no guessing.
"""

from __future__ import annotations

from dataclasses import dataclass

import phonenumbers

_MISSING_REGION = "phone number has no country code and no default_region was given"


class PhoneError(ValueError):
    """Raised when a phone number cannot be normalized."""


@dataclass(frozen=True)
class ParsedPhone:
    """A normalized phone number plus its provenance flag."""

    e164: str
    inferred_region: bool


def parse(value: str, *, default_region: str | None = None) -> ParsedPhone:
    """Normalize ``value`` to E.164.

    Raises :class:`PhoneError` when the number is missing a country code
    without an explicit ``default_region``, or when it is not possible.
    """
    text = value.strip()
    if not text:
        raise PhoneError("empty phone number")
    inferred = default_region is not None and not text.startswith("+")
    try:
        number = phonenumbers.parse(text, default_region)
    except phonenumbers.NumberParseException as exc:
        raise PhoneError(f"unparseable phone number {value!r}: {exc}") from exc
    if default_region is None and number.country_code == 0:
        raise PhoneError(_MISSING_REGION)
    if not phonenumbers.is_possible_number(number):
        raise PhoneError(f"impossible phone number {value!r}")
    return ParsedPhone(
        e164=phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164),
        inferred_region=inferred,
    )
