"""Timezone-aware time parsing (STD §2: naive timestamps are rejected)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

_DURATION_RE = re.compile(r"^(?P<amount>\d+)(?P<unit>[dhm])$")


class InvalidTimeError(ValueError):
    """Raised for naive timestamps or unparseable time input."""


def parse(value: str) -> datetime:
    """Parse ISO-8601 with an explicit offset (``Z`` accepted).

    Naive timestamps raise :class:`InvalidTimeError`; the result is
    normalized to UTC.
    """
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise InvalidTimeError(f"invalid timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        raise InvalidTimeError(f"naive timestamp rejected: {value!r}")
    return parsed.astimezone(UTC)


def from_epoch_ms(value: int) -> datetime:
    """Build an aware UTC datetime from epoch milliseconds."""
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def window(spec: str, now: datetime) -> tuple[datetime, datetime]:
    """Return the ``(start, end)`` window ending at ``now``.

    ``spec`` looks like ``30d``, ``12h`` or ``15m``. ``now`` must be
    timezone-aware; the core never reads the wall clock directly.
    """
    if now.tzinfo is None:
        raise InvalidTimeError("window() requires a timezone-aware 'now'")
    match = _DURATION_RE.match(spec.strip())
    if match is None:
        raise InvalidTimeError(f"invalid window spec {spec!r}, expected like '30d'")
    amount = int(match.group("amount"))
    unit = match.group("unit")
    delta = (
        timedelta(days=amount)
        if unit == "d"
        else timedelta(hours=amount)
        if unit == "h"
        else timedelta(minutes=amount)
    )
    return (now - delta, now)
