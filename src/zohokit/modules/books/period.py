"""Books period windowing (TK-BK-F6): month membership by the record's own date.

A record belongs to ``[start, end]`` (both bounds **inclusive**) when the
calendar date in its own timezone falls inside the window:

- ``2026-09-30T23:30:00+05:30`` (IST) belongs to September (local 30th),
  even though it is ``2026-09-30T18:00:00Z`` in UTC;
- ``2026-10-01T00:30:00+05:30`` (IST) belongs to October, even though it
  is still 30 September in UTC;
- ``2026-08-31T19:00:00-07:00`` (US-Pacific) belongs to August, even
  though it is 1 September in UTC.

In other words the comparison uses the date as written in the record's
own offset (a bare ``YYYY-MM-DD`` is that date). :func:`in_window`
treats records without a date (or with an unparseable date) as
in-window — only a dated record outside the window is excluded. The
reconciliation engine (:mod:`reconcile`) does NOT rely on that fallback
for windowed runs: a deal with a missing/unparseable ``closing_date``
or an invoice with a missing/unparseable ``date`` gets ``invalid_date``
(review) and is excluded from every matching pass, row-level
(TK-FIX-2 style) like ``invalid_amount``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


def record_date(raw: Any) -> date | None:
    """Local calendar date of an ISO date/datetime string, else ``None``."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    try:
        if "T" in text or " " in text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        return date.fromisoformat(text)
    except ValueError:
        return None


def in_window(raw: Any, *, start: date, end: date) -> bool:
    """Whether the record date *raw* falls in ``[start, end]`` (inclusive)."""
    day = record_date(raw)
    if day is None:
        return True
    return start <= day <= end


__all__: list[str] = ["in_window", "record_date"]
