"""Email normalization and candidate matching keys."""

from __future__ import annotations

import re

_SYNTAX_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailError(ValueError):
    """Raised for syntactically invalid email addresses."""


def normalize(value: str) -> str:
    """Strip and casefold an email address for comparison."""
    text = value.strip().casefold()
    if not _SYNTAX_RE.match(text):
        raise EmailError(f"invalid email syntax {value!r}")
    return text


def candidate_key(value: str) -> str:
    """Return the duplicate-detection key for an email address."""
    return normalize(value)
