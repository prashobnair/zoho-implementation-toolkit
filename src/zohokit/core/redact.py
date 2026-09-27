"""PII redaction for logs, cassettes, prompts and client reports (STD §4.5)."""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_DIGITS_RE = re.compile(r"\+?\d[\d\s\-()]{6,}\d")


def mask_email(value: str) -> str:
    """Mask an email as ``a***@example.invalid`` (STD-X1)."""
    local = value.strip().split("@")[0] if "@" in value else value.strip()
    head = local[0].casefold() if local else "x"
    return f"{head}***@example.invalid"


def mask_phone(value: str) -> str:
    """Keep only the country code and last 2 digits, mask the rest."""
    digits = re.sub(r"\D", "", value)
    if len(digits) < 4:
        return "**"
    country, rest = digits[:-10], digits[-10:]
    if not country:
        country = rest[:-7] if len(rest) > 7 else ""
        national = rest[-7:] if len(rest) >= 7 else rest
    else:
        national = rest
    masked_national = "*" * max(len(national) - 2, 0) + national[-2:]
    return f"+{country}{masked_national}" if country else masked_national


def redact_text(text: str) -> str:
    """Redact email addresses and phone-like digit runs in free text."""
    redacted = _EMAIL_RE.sub(lambda match: mask_email(match.group(0)), text)
    return _PHONE_DIGITS_RE.sub(lambda match: mask_phone(match.group(0)), redacted)
