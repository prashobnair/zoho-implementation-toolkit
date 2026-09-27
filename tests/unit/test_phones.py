"""Unit tests for phone normalization (core/phones.py scaffold)."""

from __future__ import annotations

import pytest

from zohokit.core.phones import PhoneError, parse


def test_parse_e164_with_country_code() -> None:
    parsed = parse("+1 650-253-0000")
    assert parsed.e164 == "+16502530000"
    assert parsed.inferred_region is False


def test_parse_with_explicit_region_flags_inference() -> None:
    parsed = parse("98200 11223", default_region="IN")
    assert parsed.e164 == "+919820011223"
    assert parsed.inferred_region is True


def test_parse_rejects_missing_region() -> None:
    with pytest.raises(PhoneError):
        parse("98200 11223")


def test_parse_rejects_impossible() -> None:
    with pytest.raises(PhoneError):
        parse("+1 123")
