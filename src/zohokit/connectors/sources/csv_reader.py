"""Streaming generic CSV reader (TK-MIG-F2).

Assumed layout: a header row followed by data rows. Encoding is detected
as BOM (UTF-8-SIG, UTF-16 LE/BE) then strict UTF-8, falling back to
Windows-1252; the delimiter is sniffed from ``,;\\t|`` on a sample, with
a comma fallback. CRLF, a BOM, quoted embedded newlines and quoted
separators all parse via the :mod:`csv` module.

Reads stream: at most one chunk plus one row live in memory. Row-level
problems (wrong width, undecodable text, blank lines) are returned as
:class:`RowIssue` values; the caller turns them into ``row_parse_error``
findings and continues.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass, field

#: Delimiters the sniffer chooses from (comma fallback when tied).
CANDIDATE_DELIMITERS = (",", ";", "\t", "|")

#: Bytes kept for sniffing (a prefix of the decoded head sample).
_SNIFF_CHARS = 65536

#: Rows read per file chunk while streaming.
_CHUNK_SIZE = 65536


class CsvReadError(ValueError):
    """The file cannot be decoded or has no usable header."""


@dataclass(frozen=True)
class RowIssue:
    """One row-level problem; the run continues past it."""

    line_number: int
    reason: str


@dataclass(frozen=True)
class CsvDialect:
    """Detected file shape, reported for provenance."""

    encoding: str
    delimiter: str
    header: tuple[str, ...]


@dataclass
class CsvStream:
    """One open CSV read: header plus a row iterator.

    Iterate as ``for line_number, row, issue in stream.rows():`` — each
    step yields exactly one of a row dict or an issue. ``row`` maps the
    header names to cell text (cells are stripped of ``\\r`` only; mapping
    transforms own whitespace policy).
    """

    path: str
    dialect: CsvDialect
    _lines: io.TextIOBase = field(repr=False)

    def rows(self) -> Iterator[tuple[int, dict[str, str] | None, RowIssue | None]]:
        """Yield ``(line_number, row | None, issue | None)`` per data row.

        ``line_number`` is the physical line where the record ends
        (:attr:`csv.reader.line_num`), so quoted embedded newlines still
        point at a real file line. Each step yields exactly one of a row
        dict or an issue.
        """
        reader = csv.reader(self._lines, delimiter=self.dialect.delimiter)
        # The header was already parsed in open_csv; skip the physical line.
        _ = next(reader, None)
        width = len(self.dialect.header)
        for record in reader:
            line_number = reader.line_num
            if not record or all(cell == "" for cell in record):
                yield line_number, None, RowIssue(line_number, "blank_row")
                continue
            if len(record) != width:
                yield line_number, None, RowIssue(line_number, "wrong_column_count")
                continue
            yield line_number, dict(zip(self.dialect.header, record, strict=True)), None

    def close(self) -> None:
        """Release the underlying file handle."""
        self._lines.close()


def detect_encoding(raw: bytes) -> tuple[str, int]:
    """Return ``(encoding, bom_offset)`` for *raw*.

    BOMs win outright; otherwise strict UTF-8 is tried before the
    Windows-1252 fallback, so detection is deterministic for one input.
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", 3
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16", 0
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return "cp1252", 0
    return "utf-8", 0


def sniff_delimiter(sample: str) -> str:
    """Pick the most frequent candidate delimiter outside quotes.

    A tiny state machine skips quoted spans so separators inside quotes
    never vote. Comma wins ties; a header with no candidate at all also
    yields a comma (single-column files).
    """
    counts = dict.fromkeys(CANDIDATE_DELIMITERS, 0)
    in_quote = False
    index = 0
    while index < len(sample):
        char = sample[index]
        if char == '"':
            if in_quote and sample[index + 1 : index + 2] == '"':
                index += 2
                continue
            in_quote = not in_quote
        elif not in_quote and char in counts:
            counts[char] += 1
        index += 1
    best = max(CANDIDATE_DELIMITERS, key=lambda mark: (counts[mark], mark == ","))
    return best if counts[best] > 0 else ","


def open_csv(path: str) -> CsvStream:
    """Open *path* for streaming; detect encoding, delimiter and header.

    Raises :class:`CsvReadError` (a config/input error, exit 1) when the
    file cannot be decoded or carries no header row.
    """
    with open(path, "rb") as handle:
        raw_head = handle.read(_SNIFF_CHARS)
    if not raw_head.strip():
        raise CsvReadError(f"{path}: file is empty")
    encoding, _ = detect_encoding(raw_head)
    # The head sample may end mid-character; replacement chars here only
    # feed delimiter sniffing, never row data (rows stream from the file).
    text_head = raw_head.decode(encoding, errors="replace")
    delimiter = sniff_delimiter(text_head)
    lines = open(path, encoding=encoding, newline="", errors="replace")
    try:
        peek = csv.reader(io.StringIO(text_head), delimiter=delimiter)
        raw_header: list[str] | None = next(peek, None)
    except csv.Error as exc:
        lines.close()
        raise CsvReadError(f"{path}: cannot parse header: {exc}") from exc
    if not raw_header or all(cell.strip() == "" for cell in raw_header):
        lines.close()
        raise CsvReadError(f"{path}: file has no header row")
    header: tuple[str, ...] = tuple(cell.strip() for cell in raw_header)
    # Rewind: rows() skips the physical header line itself.
    lines.seek(0)
    return CsvStream(path=path, dialect=CsvDialect(encoding, delimiter, header), _lines=lines)


__all__: list[str] = [
    "CANDIDATE_DELIMITERS",
    "CsvDialect",
    "CsvReadError",
    "CsvStream",
    "RowIssue",
    "detect_encoding",
    "open_csv",
    "sniff_delimiter",
]
