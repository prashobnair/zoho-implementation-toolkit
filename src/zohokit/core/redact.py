"""PII and credential redaction for logs, cassettes, prompts and reports (STD §4.5)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_DIGITS_RE = re.compile(r"\+?\d[\d\s\-()]{6,}\d")

_ZOHO_OAUTHTOKEN_RE = re.compile(r"Zoho-oauthtoken\s+[^\s,;\"']+", re.IGNORECASE)
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/=]+", re.IGNORECASE)
_ZOHO_TOKEN_RE = re.compile(r"\b1000\.[0-9a-fA-F]{2,}\.[0-9a-fA-F]{2,}\b")

#: Placeholder domain: scanner-tolerated, never a real mailbox.
REDACTED_DOMAIN = "example.invalid"

#: Opaque org/record fingerprints (``sha256:<hex>``) are safe to share by
#: design (report envelopes carry the fingerprint, never the raw ID), so the
#: redactor and the cassette scanner both leave them untouched.
FINGERPRINT_RE = re.compile(r"sha256:[0-9a-fA-F]{8,}")

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

#: Replacement for OAuth credentials (tokens, secrets, auth headers).
REDACTED_CREDENTIAL = "[redacted-credential]"

#: Credential-bearing keys, matched case-insensitively (STD-X1).
CREDENTIAL_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "client_secret",
        "client_id",
        "id_token",
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
    }
)

#: Keys whose presence marks a dict as a token exchange: a sibling
#: ``code`` there is the OAuth grant code, not a finding code.
_TOKEN_CONTEXT_KEYS = frozenset(
    {
        "grant_type",
        "refresh_token",
        "access_token",
        "client_secret",
        "client_id",
        "id_token",
        "redirect_uri",
    }
)


def mask_email(value: str) -> str:
    """Mask an email as ``a***@example.invalid`` (STD-X1)."""
    local = value.strip().split("@")[0] if "@" in value else value.strip()
    head = local[0].casefold() if local else "x"
    return f"{head}***@{REDACTED_DOMAIN}"


def mask_phone(value: str) -> str:
    """Mask a phone, keeping the country code only when one was given.

    Inputs with a leading ``+`` keep ``+<country><masked><last2>``; local
    numbers without ``+`` never gain one — every digit but the last 2 is
    masked (``9876543210`` → ``********10``).
    """
    text = value.strip()
    has_plus = text.startswith("+")
    digits = re.sub(r"\D", "", value)
    if len(digits) < 4:
        return "**"
    if not has_plus:
        return "*" * (len(digits) - 2) + digits[-2:]
    country, rest = digits[:-10], digits[-10:]
    if not country:
        country = rest[:-7] if len(rest) > 7 else ""
        national = rest[-7:] if len(rest) >= 7 else rest
    else:
        national = rest
    masked_national = "*" * max(len(national) - 2, 0) + national[-2:]
    return f"+{country}{masked_national}" if country else masked_national


def _redact_credential_patterns(text: str) -> str:
    redacted = _ZOHO_OAUTHTOKEN_RE.sub(f"Zoho-oauthtoken {REDACTED_CREDENTIAL}", text)
    redacted = _BEARER_RE.sub(f"Bearer {REDACTED_CREDENTIAL}", redacted)
    return _ZOHO_TOKEN_RE.sub(REDACTED_CREDENTIAL, redacted)


#: Splitter that keeps ``sha256:<hex>`` fingerprints as separate chunks.
_FINGERPRINT_SPLIT_RE = re.compile(r"(sha256:[0-9a-fA-F]{8,})")


def _redact_segment(segment: str) -> str:
    redacted = _redact_credential_patterns(segment)
    redacted = _EMAIL_RE.sub(lambda match: mask_email(match.group(0)), redacted)
    return _PHONE_DIGITS_RE.sub(lambda match: mask_phone(match.group(0)), redacted)


def redact_text(text: str) -> str:
    """Redact credentials, then emails and phone-like digit runs.

    ``sha256:<hex>`` fingerprints are opaque by design and pass through
    untouched so evidence keeps a stable org identity.
    """
    chunks = _FINGERPRINT_SPLIT_RE.split(text)
    return "".join(
        chunk if _FINGERPRINT_SPLIT_RE.fullmatch(chunk) else _redact_segment(chunk)
        for chunk in chunks
    )


@dataclass(frozen=True)
class Redactor:
    """Shared structured redactor (STD-X1).

    Masks emails (``a***@example.invalid``), phones (country code + last
    2 digits), configured person-name fields, and any field tagged
    ``pii: true``. OAuth credential keys and token patterns are replaced
    with ``[redacted-credential]``. Applied to logs, cassettes, evidence
    and client-audience reports.
    """

    name_fields: frozenset[str] = DEFAULT_NAME_FIELDS
    pii_fields: frozenset[str] = field(default_factory=frozenset)

    def redact_value(self, key: str, value: Any) -> Any:
        """Redact one field value by its field name."""
        lowered = key.casefold()
        if lowered in CREDENTIAL_KEYS:
            return REDACTED_CREDENTIAL
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
            lowered_keys = {str(key).casefold() for key in value}
            token_context = bool(lowered_keys & _TOKEN_CONTEXT_KEYS)
            redacted: dict[Any, Any] = {}
            for key, item in value.items():
                lowered = str(key).casefold()
                if lowered in CREDENTIAL_KEYS:
                    redacted[key] = REDACTED_CREDENTIAL
                elif lowered == "code" and token_context:
                    redacted[key] = REDACTED_CREDENTIAL
                else:
                    redacted[key] = self.redact_value(str(key), item)
            return redacted
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
    "CREDENTIAL_KEYS",
    "DEFAULT_NAME_FIELDS",
    "FINGERPRINT_RE",
    "REDACTED_CREDENTIAL",
    "REDACTED_DOMAIN",
    "REDACTED_VALUE",
    "Redactor",
    "mask_email",
    "mask_phone",
    "redact_text",
]
