"""Books FX-rate table (TK-BK-F3): exact rates only, never guessed.

The table is a CSV file with header ``date,from,to,rate,source``::

    date,from,to,rate,source
    2026-09-15,USD,INR,88.2500,RBI reference rate
    2026-09-30,USD,INR,88.4100,RBI reference rate

Lookup is exact on ``(date, from, to)``: when no row covers the
conversion, the caller emits ``fx_rate_missing`` (review) and skips the
comparison. The engine never interpolates, never picks the nearest
date, and never inverts an unrelated pair. All arithmetic uses
:class:`Decimal` (never float): rates parse through a strict decimal
grammar with up to 6 places.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path


@dataclass(frozen=True)
class FxRate:
    """One published rate: 1 unit of ``frm`` costs ``rate`` units of ``to``."""

    on: date
    frm: str
    to: str
    rate: Decimal
    source: str


class FxConfigError(ValueError):
    """An FX-table problem as ``path:line: detail`` (exit 1 at the CLI)."""

    def __init__(self, path: str | Path, line: int, detail: str) -> None:
        super().__init__(f"{path}:{line}: {detail}")
        self.path = str(path)
        self.line = line
        self.detail = detail


_FX_HEADER = ("date", "from", "to", "rate", "source")


def _parse_rate(raw: str, *, path: str | Path, line: int) -> Decimal:
    """Strict positive decimal rate (no floats, at most 6 places)."""
    text = raw.strip()
    try:
        rate = Decimal(text)
    except InvalidOperation as exc:
        raise FxConfigError(str(path), line, "fx rate must be a decimal number") from exc
    if not rate.is_finite() or rate <= 0:
        raise FxConfigError(str(path), line, "fx rate must be a positive number")
    exponent = rate.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -6:
        raise FxConfigError(str(path), line, "fx rate exceeds 6 decimal places")
    return rate


def load_fx_rates(path: Path) -> tuple[FxRate, ...]:
    """Load and validate an FX-rate CSV file (UTF-8, exact header)."""
    text_path = Path(path)
    try:
        text = text_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise FxConfigError(str(path), 1, f"cannot read fx table: {exc}") from exc
    lines = text.splitlines()
    if not lines:
        raise FxConfigError(str(path), 1, "fx table is empty")
    reader = csv.reader(lines)
    header = next(reader)
    if tuple(cell.strip().casefold() for cell in header) != _FX_HEADER:
        raise FxConfigError(str(path), 1, "fx table header must be date,from,to,rate,source")
    rates: list[FxRate] = []
    for number, row in enumerate(reader, start=2):
        if not row or all(not cell.strip() for cell in row):
            continue
        if len(row) != 5:
            raise FxConfigError(str(path), number, "fx row must have 5 columns")
        day_raw, frm_raw, to_raw, rate_raw, source_raw = (cell.strip() for cell in row)
        try:
            day = date.fromisoformat(day_raw)
        except ValueError as exc:
            raise FxConfigError(str(path), number, "fx date must be YYYY-MM-DD") from exc
        frm = frm_raw.upper()
        to = to_raw.upper()
        if not frm or not to:
            raise FxConfigError(str(path), number, "fx from/to must be non-empty")
        rate = _parse_rate(rate_raw, path=path, line=number)
        rates.append(FxRate(on=day, frm=frm, to=to, rate=rate, source=source_raw))
    return tuple(rates)


def lookup_rate(rates: tuple[FxRate, ...], *, on: date, frm: str, to: str) -> FxRate | None:
    """Exact ``(date, from, to)`` lookup; ``None`` when uncovered.

    Same-currency pairs need no row (callers skip the lookup). Reverse
    pairs never invert implicitly — a missing row is ``None``.
    """
    if frm.upper() == to.upper():
        return None
    for rate in rates:
        if rate.on == on and rate.frm == frm.upper() and rate.to == to.upper():
            return rate
    return None


def convert(amount: Decimal, rate: FxRate) -> Decimal:
    """Convert *amount* (in ``rate.frm``) to ``rate.to`` units (Decimal only)."""
    return amount * rate.rate


__all__: list[str] = [
    "FxConfigError",
    "FxRate",
    "convert",
    "load_fx_rates",
    "lookup_rate",
]
