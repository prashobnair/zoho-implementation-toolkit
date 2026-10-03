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
#:
#: ``name`` on its own is intentionally absent here: the bare key is also
#: the structural label of doctor checks and smoke reads
#: (``{"name": ..., "status": ...}``). Bare ``name`` is handled by
#: :data:`PII_KEY_SUBSTRINGS` with a check/read context exception instead
#: (see :func:`_pii_kind`), so ``api_name``-style metadata survives via
#: :data:`STRUCTURAL_KEYS` while ``{"First_Name": ...}``-style person data
#: is still masked.
DEFAULT_NAME_FIELDS = frozenset(
    {
        "first_name",
        "last_name",
        "full_name",
        "contact_name",
        "owner_name",
        "account_name",
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

#: Key substrings masked by name alone, independent of value format
#: (STD-X1): any key (case-insensitive, at any depth, after stripping
#: Zoho's ``$`` prefix) containing one of these is PII. Phone/email keys
#: keep their shaped masks (:func:`mask_phone`/:func:`mask_email`); every
#: other match becomes ``[redacted]``.
#:
#: ``name`` is in this list but needs care: it also matches structural
#: metadata (``api_name``, ``module_name``) and the ``name`` label of
#: doctor checks / smoke reads. Those survive via :data:`STRUCTURAL_KEYS`
#: and the check/read context exception in :func:`_pii_kind`.
PII_KEY_SUBSTRINGS = (
    "phone",
    "mobile",
    "fax",
    "email",
    "zip",
    "street",
    "address",
    "skype",
    "twitter",
    "website",
    "full_name",
    "first_name",
    "last_name",
    "name",
    "dob",
    "date_of_birth",
    "zuid",
    "zgid",
    "primary_zuid",
    "primary_email",
    "photo_id",
    "domain_name",
)

#: Structural keys that must NEVER be masked even though they contain a
#: :data:`PII_KEY_SUBSTRINGS` entry (all matched case-insensitively after
#: stripping a leading ``$``):
#:
#: - ``api_name`` / ``api_names`` / ``module_name``: field and module
#:   metadata (shapes-only evidence lists these by design);
#: - ``id``: record/org identifiers pass through untouched (opaque
#:   ``sha256:`` fingerprints and the scanner's configured-ID check own
#:   them, as already designed).
STRUCTURAL_KEYS = frozenset({"api_name", "api_names", "module_name", "id"})

#: Numeric time-zone offsets in milliseconds are structural, not PII: the
#: lead-verified recording run showed ``"offset": 19800000`` on a CRM users
#: entry (19,800,000 ms = IST, UTC+5:30). Users endpoint docs (doc URL as
#: recorded in ``docs/API_CONTRACTS.md``):
#: https://www.zoho.com/crm/developer/docs/api/v8/get-users.html
#: Narrow allowlist: only the ``offset`` key (no other key could be
#: justified without fetching the Zoho docs, which this repo never does),
#: and only when the value is an integer (a JSON number or an all-digit
#: string with an optional sign) within +/-50400000 (+/-14 h in ms).
#: Mirrored in ``scripts/cassette_scan.py`` (which stays import-free), so
#: the recorder (redacts before write) and the scan gate agree.
STRUCTURAL_TZ_KEYS = frozenset({"offset"})

#: Largest valid time-zone offset: +/-14 h in milliseconds.
MAX_TZ_OFFSET_MS = 50400000

_TZ_OFFSET_STR_RE = re.compile(r"[-+]?[0-9]+")


def is_structural_tz_offset(key: str, value: object) -> bool:
    """True for an in-range ``offset`` integer (number or digit string).

    Anything else — out-of-range numbers, non-numeric strings, other keys —
    returns False so the normal redaction/scan rules still apply.
    """
    if _normalize_key(key) not in STRUCTURAL_TZ_KEYS or isinstance(value, bool):
        return False
    if isinstance(value, int):
        return abs(value) <= MAX_TZ_OFFSET_MS
    if isinstance(value, str):
        text = value.strip()
        if _TZ_OFFSET_STR_RE.fullmatch(text) is None:
            return False
        return abs(int(text)) <= MAX_TZ_OFFSET_MS
    return False


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

    Idempotent: a value that already carries ``*`` masking passes through
    untouched, so re-running the redactor (``scrub_cassettes`` over a
    freshly recorded cassette) is a byte-identical no-op.
    """
    text = value.strip()
    if "*" in text:
        return text
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


def _normalize_key(key: object) -> str:
    """Lower-cased key with Zoho's ``$`` prefix stripped for matching."""
    return str(key).casefold().lstrip("$")


def _pii_kind(normalized: str, *, is_check_or_read: bool) -> str | None:
    """Classify a normalized key: ``"phone"``, ``"email"``, ``"generic"`` or None.

    ``is_check_or_read`` marks dicts shaped like a doctor check or a smoke
    read (a ``name`` next to a ``status`` plus a ``detail``/``endpoint``):
    there the bare ``name`` key is the structural label (``org_identity``,
    ``Leads``, ...), not a person, so only it is exempted. Every other
    ``*name*`` key (``company_name``, ``Last_Name``, ``Deal_Name``, ...)
    stays masked.
    """
    if normalized in STRUCTURAL_KEYS:
        return None
    if normalized == "name" and is_check_or_read:
        return None
    if "phone" in normalized or "mobile" in normalized or "fax" in normalized:
        return "phone"
    if "email" in normalized:
        return "email"
    for substring in PII_KEY_SUBSTRINGS:
        if substring and substring in normalized:
            return "generic"
    return None


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

    Key-based PII masking, independent of value format: any key
    (case-insensitive, nested at any depth, after stripping Zoho's ``$``
    prefix) containing a :data:`PII_KEY_SUBSTRINGS` entry is masked —
    phone/email keys keep their shaped masks (``mask_phone`` /
    ``mask_email``), every other match becomes ``[redacted]``. Also masks
    configured person-name fields, ``pii_fields``, and free-text emails,
    phones and OAuth credential patterns in any string. OAuth credential
    keys are replaced with ``[redacted-credential]``.

    Structural keys in :data:`STRUCTURAL_KEYS` (``api_name``,
    ``api_names``, ``module_name``, ``id``) are never masked by name, and
    the bare ``name`` of a doctor check or smoke read (a ``name`` next to
    a ``status`` plus a ``detail``/``endpoint``) is the checklist label,
    not a person, so it survives too. Applied to logs, cassettes,
    evidence and client-audience reports.
    """

    name_fields: frozenset[str] = DEFAULT_NAME_FIELDS
    pii_fields: frozenset[str] = field(default_factory=frozenset)

    def redact_value(self, key: str, value: Any, *, is_check_or_read: bool = False) -> Any:
        """Redact one field value by its field name."""
        lowered = key.casefold()
        normalized = _normalize_key(key)
        if lowered in CREDENTIAL_KEYS or normalized in CREDENTIAL_KEYS:
            return REDACTED_CREDENTIAL
        if lowered in self.name_fields or normalized in self.name_fields:
            return REDACTED_VALUE
        if lowered in self.pii_fields or normalized in self.pii_fields:
            return REDACTED_VALUE
        if is_structural_tz_offset(key, value):
            return value
        kind = _pii_kind(normalized, is_check_or_read=is_check_or_read)
        if kind == "phone":
            if isinstance(value, str):
                return mask_phone(value)
            if isinstance(value, int):
                return mask_phone(str(value))
            if value is None:
                return None
            return REDACTED_VALUE
        if kind == "email":
            if isinstance(value, str):
                return mask_email(value) if "@" in value else redact_text(value)
            if value is None:
                return None
            return REDACTED_VALUE
        if kind == "generic":
            if value is None:
                return None
            return REDACTED_VALUE
        if isinstance(value, str):
            return redact_text(value)
        return self.redact_obj(value)

    def redact_obj(self, value: Any) -> Any:
        """Recursively redact dicts, lists and strings."""
        if isinstance(value, dict):
            lowered_keys = {str(key).casefold() for key in value}
            normalized_keys = {_normalize_key(key) for key in value}
            token_context = bool(
                lowered_keys & _TOKEN_CONTEXT_KEYS or normalized_keys & _TOKEN_CONTEXT_KEYS
            )
            # A doctor check or a smoke read carries its structural label in
            # ``name`` next to a ``status`` plus a ``detail`` (checks) or an
            # ``endpoint`` (reads). That ``name`` (``org_identity``,
            # ``Leads``, ...) is never a person. A bare ``name`` anywhere
            # else — including a user/record entry that happens to carry a
            # ``status`` — is still masked.
            is_check_or_read = (
                "name" in normalized_keys
                and "status" in normalized_keys
                and ("detail" in normalized_keys or "endpoint" in normalized_keys)
            )
            redacted: dict[Any, Any] = {}
            for key, item in value.items():
                lowered = str(key).casefold()
                normalized = _normalize_key(key)
                if lowered in CREDENTIAL_KEYS or normalized in CREDENTIAL_KEYS:
                    redacted[key] = REDACTED_CREDENTIAL
                elif (lowered == "code" or normalized == "code") and token_context:
                    redacted[key] = REDACTED_CREDENTIAL
                elif normalized in STRUCTURAL_KEYS:
                    # Metadata (``api_name``, ...) survives by key, but its
                    # value is still swept for free-text emails/phones.
                    redacted[key] = (
                        redact_text(item) if isinstance(item, str) else self.redact_obj(item)
                    )
                else:
                    redacted[key] = self.redact_value(
                        str(key), item, is_check_or_read=is_check_or_read
                    )
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
    "MAX_TZ_OFFSET_MS",
    "PII_KEY_SUBSTRINGS",
    "REDACTED_CREDENTIAL",
    "REDACTED_DOMAIN",
    "REDACTED_VALUE",
    "STRUCTURAL_KEYS",
    "STRUCTURAL_TZ_KEYS",
    "Redactor",
    "is_structural_tz_offset",
    "mask_email",
    "mask_phone",
    "redact_text",
]
