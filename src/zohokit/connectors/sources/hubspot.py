"""HubSpot CSV export layout (TK-MIG-F2, TK-CONN-8).

Assumed layout (from the HubSpot view "Export" action, one file per
object): contacts, companies and deals CSVs with a header row. The
column sets below are the export defaults; extra columns ride along
untouched, missing optional columns are tolerated, and a missing
*required* column is a config error naming the column.

- contacts: ``Contact ID, First Name, Last Name, Email, Phone Number,
  Associated Company IDs, Create Date``
- companies: ``Company ID, Company Name, Country, Create Date``
- deals: ``Deal ID, Deal Name, Associated Contact IDs, Associated Company
  IDs, Amount, Currency, Deal Stage, Pipeline, Create Date``

All reads stream through :mod:`csv_reader`; row-level problems surface
as issues, never as aborts.
"""

from __future__ import annotations

from collections.abc import Iterator

from zohokit.connectors.sources.csv_reader import CsvReadError, CsvStream, RowIssue, open_csv

#: Required columns per HubSpot file kind (missing → config error).
REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "contacts": ("Contact ID", "Email"),
    "companies": ("Company ID", "Company Name"),
    "deals": ("Deal ID", "Deal Name", "Deal Stage"),
}


class HubSpotLayoutError(ValueError):
    """A HubSpot file misses a required column (config error, exit 1)."""


def open_kind(path: str, *, kind: str) -> CsvStream:
    """Open a HubSpot *kind* file; check its required columns.

    Raises :class:`HubSpotLayoutError` naming the missing column when
    the header lacks one. Unknown *kind* is also a config error.
    """
    try:
        required = REQUIRED_COLUMNS[kind]
    except KeyError as exc:
        raise HubSpotLayoutError(f"unknown HubSpot kind {kind!r}") from exc
    try:
        stream = open_csv(path)
    except CsvReadError as exc:
        raise HubSpotLayoutError(str(exc)) from exc
    missing = [column for column in required if column not in stream.dialect.header]
    if missing:
        stream.close()
        raise HubSpotLayoutError(f"{path}: HubSpot {kind} file misses column(s): {missing}")
    return stream


def iter_rows(stream: CsvStream) -> Iterator[tuple[int, dict[str, str] | None, RowIssue | None]]:
    """Yield ``(line_number, row | None, issue | None)`` from *stream*."""
    yield from stream.rows()


__all__: list[str] = ["REQUIRED_COLUMNS", "HubSpotLayoutError", "iter_rows", "open_kind"]
