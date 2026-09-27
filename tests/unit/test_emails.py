"""Unit tests for email normalization (core/emails.py scaffold)."""

from __future__ import annotations

import pytest

from zohokit.core.emails import EmailError, candidate_key, normalize


def test_normalize_casefolds_and_strips() -> None:
    assert normalize("  Alice@Example.COM ") == "alice@example.com"


def test_normalize_rejects_bad_syntax() -> None:
    with pytest.raises(EmailError):
        normalize("not-an-email")


def test_candidate_key_matches_normalize() -> None:
    assert candidate_key("BOB@Example.com") == normalize("bob@example.COM")
