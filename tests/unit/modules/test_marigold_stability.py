"""Marigold stability: finding IDs survive row shifts and shuffles (TK-MIG).

Per-record findings key on the stable source record ID (never a
position) with the physical file line in evidence only, so prepending a
row or shuffling rows changes no finding ID and no cluster survivor.
Two finding classes are inherently input-dependent and excluded from
the ID comparison, with rationale inline: ``row_parse_error`` is
positional by design (a parse fault has no record to key on) and
``target_dedupe_coverage`` reports checked/total counts.
"""

from __future__ import annotations

import csv
import json
import random
import shutil
from datetime import UTC, datetime
from pathlib import Path

from zohokit.core.context import RunContext
from zohokit.core.findings import Report
from zohokit.modules.migration.mapping import load_mapping
from zohokit.modules.migration.metadata import metadata_from_dir
from zohokit.modules.migration.owners import users_from_file
from zohokit.modules.migration.preflight import ExtraChecks, SourceSpec, run_preflight
from zohokit.modules.migration.target_dedupe import target_fingerprint

ROOT = Path(__file__).resolve().parent.parent.parent.parent
MARIGOLD = ROOT / "fixtures" / "migration" / "marigold"

CTX = RunContext(now=datetime(2026, 1, 5, tzinfo=UTC))

#: Codes excluded from cross-run ID equality (input-dependent by design).
EXCLUDED_CODES = frozenset({"row_parse_error", "target_dedupe_coverage"})


def _report_over(source_dir: Path) -> Report:
    """Run the Marigold preflight over *source_dir* (offline search)."""
    doc = load_mapping(MARIGOLD / "mapping.yaml")
    sources = {
        entity.name: SourceSpec(
            path=str(source_dir / f"{entity.source_kind}.csv"),
            kind=entity.source_kind,
        )
        for entity in doc.entities
    }
    metadata = metadata_from_dir(MARIGOLD / "fields")
    users = users_from_file(MARIGOLD / "users.json")
    snapshot = json.loads((MARIGOLD / "target_existing.json").read_text(encoding="utf-8"))
    contacts = snapshot.get("Contacts", [])
    assert isinstance(contacts, list)
    by_email = {
        str(record["Email"]).casefold(): target_fingerprint(str(record["id"]))
        for record in contacts
        if isinstance(record, dict) and record.get("Email") and record.get("id")
    }

    def search(module: str, email: str | None, phone: str | None) -> list[str]:
        _ = (module, phone)
        if email is None:
            return []
        match = by_email.get(email.casefold())
        return [match] if match is not None else []

    return run_preflight(
        doc, sources, metadata, ctx=CTX, extra=ExtraChecks(users=users, search=search)
    )


def _stable_ids(report: Report) -> set[str]:
    """Finding IDs excluding the input-dependent codes."""
    return {finding.id for finding in report.findings if finding.code not in EXCLUDED_CODES}


def _survivors(report: Report) -> dict[str, str]:
    """Duplicate-cluster survivor per entity."""
    return {
        finding.entity: str(finding.evidence["survivor"])
        for finding in report.findings
        if finding.code == "fuzzy_duplicate_cluster"
    }


def _copy_sources(tmp_path: Path) -> Path:
    """Copy the Marigold source dir into scratch space."""
    target = tmp_path / "source"
    shutil.copytree(MARIGOLD / "source", target)
    return target


def test_prepend_row_changes_no_finding_id(tmp_path: Path) -> None:
    source_dir = _copy_sources(tmp_path)
    persons = source_dir / "persons.csv"
    lines = persons.read_text(encoding="utf-8").splitlines(keepends=True)
    header, body = lines[0], lines[1:]
    new_row = (
        "9999,Prepend Test,prepend.unique@example.invalid,"
        "+919009999999,1,web,owner@example.invalid,2026-01-02\n"
    )
    persons.write_text(header + new_row + "".join(body), encoding="utf-8")
    assert _stable_ids(_report_over(source_dir)) == _stable_ids(_report_over(MARIGOLD / "source"))


def test_shuffle_rows_changes_no_finding_id_or_survivor(tmp_path: Path) -> None:
    source_dir = _copy_sources(tmp_path)
    persons = source_dir / "persons.csv"
    lines = persons.read_text(encoding="utf-8").splitlines(keepends=True)
    header, body = lines[0], lines[1:]
    # Shuffle the first 100 physical lines only: every seeded defect row
    # stays inside the head sample whatever the order, while pair order,
    # duplicate positions and parse-error lines all move.
    head, tail = body[:100], body[100:]
    shuffled = list(head)
    random.Random(20261004).shuffle(shuffled)
    assert shuffled != head
    persons.write_text(header + "".join(shuffled) + "".join(tail), encoding="utf-8")
    before = _report_over(MARIGOLD / "source")
    after = _report_over(source_dir)
    assert _stable_ids(after) == _stable_ids(before)
    assert _survivors(after) == _survivors(before) == {"people": "31", "companies": "501"}


def _physical_line(source_file: Path, record_id: str) -> int:
    """1-based physical file line of the row whose ID column matches (header = line 1)."""
    with open(source_file, encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        assert "ID" in header
        for number, row in enumerate(reader, start=2):
            if len(row) == len(header) and row[header.index("ID")] == record_id:
                return number
    raise AssertionError(f"ID {record_id} not found in {source_file}")


def test_reported_line_matches_physical_file_line() -> None:
    """Three named seeded defects: evidence line equals the physical file line."""
    report = _report_over(MARIGOLD / "source")
    by_key = {(f.entity, f.code, f.entity_id): f for f in report.findings}
    cases = [
        ("people", "type_incompatible", "41", "persons.csv"),
        ("deals", "picklist_value_missing", "101", "deals.csv"),
        ("activities", "history_type_unsupported", "12", "activities.csv"),
    ]
    assert len(cases) == 3
    for entity, code, source_id, filename in cases:
        finding = by_key[(entity, code, source_id)]
        assert finding.evidence["line"] == _physical_line(MARIGOLD / "source" / filename, source_id)
