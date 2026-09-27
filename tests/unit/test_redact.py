"""Unit tests for PII redaction (STD-X1 scaffold)."""

from __future__ import annotations

from zohokit.core.redact import mask_email, mask_phone, redact_text


def test_mask_email_hides_local_and_domain() -> None:
    assert mask_email("Alice@Example.COM") == "a***@example.invalid"


def test_mask_phone_keeps_country_and_last_two() -> None:
    masked = mask_phone("+919820011223")
    assert masked.endswith("23")
    assert "8200112" not in masked


def test_redact_text_masks_both() -> None:
    text = redact_text("Contact alice@example.com or +1 650-253-0000 today")
    assert "alice@example.com" not in text
    assert "650-253-0000" not in text
    assert "example.invalid" in text
