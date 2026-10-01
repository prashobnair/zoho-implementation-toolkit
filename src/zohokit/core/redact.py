"""PII redaction for logs, cassettes, prompts and client reports (STD §4.5)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_DIGITS_RE = re.compile(r"\+?\d[\d\s\-()]{6,}\d")

#: Placeholder domain: scanner-tolerated, never a real mailbox.
REDACTED_DOMAIN = "example.invalid"

#: Person-name fields masked wherever the redactor sees them (STD-X1).
DEFAULT_NAME_FIELDS = frozenset(
    {
        "first_name",
        "last_name",
        "full_name",
        "contact_name",
        "owner_name",
        "account_name",
        "name",
    }
)

#: Replacement for fully-suppressed values (names, pii-tagged fields).
REDACTED_VALUE = "[redacted]"


def mask_email(value: str) -> str:
    """Mask an email as ``a***@example.invalid`` (STD-X1)."""
    local = value.strip().split("@")[0] if "@" in value else value.strip()
    head = local[0].casefold() if local else "x"
    return f"{head}***@{REDACTED_DOMAIN}"


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


@dataclass(frozen=True)
class Redactor:
    """Shared structured redactor (STD-X1).

    Masks emails (``a***@example.invalid``), phones (country code + last
    2 digits), configured person-name fields, and any field tagged
    ``pii: true``. Applied to logs, cassettes, evidence and
    client-audience reports.
    """

    name_fields: frozenset[str] = DEFAULT_NAME_FIELDS
    pii_fields: frozenset[str] = field(default_factory=frozenset)

    def redact_value(self, key: str, value: Any) -> Any:
        """Redact one field value by its field name."""
        lowered = key.casefold()
        if lowered in self.name_fields or lowered in self.pii_fields:
            return REDACTED_VALUE
        if isinstance(value, str):
            if "email" in lowered:
                return mask_email(value) if "@" in value else redact_text(value)
            if "phone" in lowered or "mobile" in lowered or "fax" in lowered:
                return mask_phone(value)
            return redact_text(value)
        return self.redact_obj(value)

    def redact_obj(self, value: Any) -> Any:
        """Recursively redact dicts, lists and strings."""
        if isinstance(value, dict):
            return {k: self.redact_value(str(k), v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact_obj(item) for item in value]
        if isinstance(value, str):
            return redact_text(value)
        return value

    def redact_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Redact one flat record (cassette entries, evidence rows)."""
        redacted = self.redact_obj(record)
        if not isinstance(redacted, dict):
            raise TypeError(f"expected a record dict, got {type(redacted).__name__}")
        return redacted


__all__: list[str] = [
    "DEFAULT_NAME_FIELDS",
    "REDACTED_DOMAIN",
    "REDACTED_VALUE",
    "Redactor",
    "mask_email",
    "mask_phone",
    "redact_text",
]
