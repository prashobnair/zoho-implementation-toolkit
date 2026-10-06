"""Pipedrive CSV export layout (TK-MIG-F2, TK-CONN-8).

Assumed layout (from the Pipedrive "Export" dialog, one file per object):
persons, organizations, deals and activities CSVs with a header row. The
column sets below are the export defaults; extra columns ride along
untouched, missing optional columns are tolerated, and a missing
*required* column is a config error naming the column.

- persons: ``ID, Name, Email, Phone, Organization ID, Created``
- organizations: ``ID, Name, Country, Created``
- deals: ``ID, Title, Person ID, Organization ID, Value, Currency, Stage,
  Status, Created``
- activities: ``ID, Subject, Deal ID, Type, Due date, Created``

All reads stream through :mod:`csv_reader`; row-level problems surface
as issues, never as aborts.
"""

from __future__ import annotations

from collections.abc import Iterator

from zohokit.connectors.sources.csv_reader import CsvReadError, CsvStream, RowIssue, open_csv

#: Required columns per Pipedrive file kind (missing → config error).
REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "persons": ("ID", "Name", "Email"),
    "organizations": ("ID", "Name"),
    "deals": ("ID", "Title", "Stage"),
    "activities": ("ID", "Subject"),
}


class PipedriveLayoutError(ValueError):
    """A Pipedrive file misses a required column (config error, exit 1)."""


def open_kind(path: str, *, kind: str) -> CsvStream:
    """Open a Pipedrive *kind* file; check its required columns.

    Raises :class:`PipedriveLayoutError` naming the missing column when
    the header lacks one. Unknown *kind* is also a config error.
    """
    try:
        required = REQUIRED_COLUMNS[kind]
    except KeyError as exc:
        raise PipedriveLayoutError(f"unknown Pipedrive kind {kind!r}") from exc
    try:
        stream = open_csv(path)
    except CsvReadError as exc:
        raise PipedriveLayoutError(str(exc)) from exc
    missing = [column for column in required if column not in stream.dialect.header]
    if missing:
        stream.close()
        raise PipedriveLayoutError(f"{path}: Pipedrive {kind} file misses column(s): {missing}")
    return stream


def iter_rows(stream: CsvStream) -> Iterator[tuple[int, dict[str, str] | None, RowIssue | None]]:
    """Yield ``(line_number, row | None, issue | None)`` from *stream*."""
    yield from stream.rows()


__all__: list[str] = ["REQUIRED_COLUMNS", "PipedriveLayoutError", "iter_rows", "open_kind"]
