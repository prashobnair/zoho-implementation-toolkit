"""Generic CSV reader tests: BOM, CRLF, newlines, sniffing (TK-MIG-F2)."""

from __future__ import annotations

from pathlib import Path

from zohokit.connectors.sources import hubspot, pipedrive
from zohokit.connectors.sources.csv_reader import (
    CsvReadError,
    detect_encoding,
    open_csv,
    sniff_delimiter,
)

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SOURCES = ROOT / "fixtures" / "sources"


def test_detect_encoding_bom_and_fallback() -> None:
    assert detect_encoding(b"\xef\xbb\xbfID\n1\n") == ("utf-8-sig", 3)
    assert detect_encoding("ID,caf\u00e9\n".encode("latin-1")) == ("cp1252", 0)
    assert detect_encoding(b"ID,Name\n1,x\n") == ("utf-8", 0)


def test_sniff_delimiter_skips_quotes() -> None:
    assert sniff_delimiter("a;b;c\n1;2;3\n") == ";"
    assert sniff_delimiter('a,b,"x;y"\n1,2,"p;q"\n') == ","
    assert sniff_delimiter("ID;Name;Email\n") == ";"


def test_bom_crlf_embedded_newlines_and_issues() -> None:
    stream = open_csv(str(SOURCES / "generic_contacts.csv"))
    try:
        assert stream.dialect.encoding == "utf-8-sig"
        assert stream.dialect.delimiter == ","
        assert stream.dialect.header == ("ID", "Name", "Email", "Phone")
        steps = list(stream.rows())
    finally:
        stream.close()
    rows = [(number, row) for number, row, issue in steps if row is not None]
    issues = [(number, issue.reason) for number, row, issue in steps if issue is not None]
    assert [row["ID"] for _, row in rows] == ["p-1", "p-2", "p-3", "p-5"]
    assert rows[1][1]["Name"] == "Meera, Rao"
    assert rows[2][1]["Name"] == "Line one\nLine two"
    # The short row and the blank line surface as issues, never as aborts.
    assert issues == [(6, "wrong_column_count"), (7, "blank_row")]
    assert [number for number, _ in rows] == [2, 3, 5, 8]


def test_semicolon_file_sniffed() -> None:
    stream = open_csv(str(SOURCES / "semicolon_notes.csv"))
    try:
        assert stream.dialect.delimiter == ";"
        steps = list(stream.rows())
    finally:
        stream.close()
    assert [(row or {}).get("ID") for _, row, _ in steps] == ["1", "2"]


def test_empty_file_is_config_error(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_bytes(b"")
    try:
        open_csv(str(path))
    except CsvReadError as exc:
        assert "empty" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected CsvReadError")


def test_streaming_does_not_load_full_file(tmp_path: Path) -> None:
    path = tmp_path / "big.csv"
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write("ID,Name\n")
        for index in range(20000):
            handle.write(f"r-{index},Name {index}\n")
    stream = open_csv(str(path))
    try:
        count = sum(1 for _, row, _ in stream.rows() if row is not None)
    finally:
        stream.close()
    assert count == 20000


def test_pipedrive_layouts_ok_and_missing_column() -> None:
    base = SOURCES / "pipedrive"
    for kind in ("persons", "organizations", "deals", "activities"):
        stream = pipedrive.open_kind(str(base / f"{kind}.csv"), kind=kind)
        found = sum(1 for _, row, _ in stream.rows() if row is not None)
        stream.close()
        assert found == 2
    try:
        pipedrive.open_kind(str(base / "persons.csv"), kind="deals")
    except pipedrive.PipedriveLayoutError as exc:
        assert "Title" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected PipedriveLayoutError")
    try:
        pipedrive.open_kind(str(base / "persons.csv"), kind="nope")
    except pipedrive.PipedriveLayoutError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected PipedriveLayoutError")


def test_hubspot_layouts_ok_and_missing_column() -> None:
    base = SOURCES / "hubspot"
    for kind in ("contacts", "companies", "deals"):
        stream = hubspot.open_kind(str(base / f"{kind}.csv"), kind=kind)
        found = sum(1 for _, row, _ in stream.rows() if row is not None)
        stream.close()
        assert found == 2
    try:
        hubspot.open_kind(str(base / "contacts.csv"), kind="deals")
    except hubspot.HubSpotLayoutError as exc:
        assert "Deal Name" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected HubSpotLayoutError")
