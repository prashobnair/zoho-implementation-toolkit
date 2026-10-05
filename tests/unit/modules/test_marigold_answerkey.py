"""Marigold answer-key test: every seeded defect detected, nothing else (TK-MIG).

Runs preflight over ``fixtures/migration/marigold/`` with a search
closure built from the checked-in ``target_existing.json`` (offline
stand-in for the live target). Asserts exact set equality between the
detected ``(entity, code, source_id, line, severity)`` tuples and the
row-level ``answer_key.json``: 100% of seeded defects detected with the
expected code and stable source key, and zero unexpected
error-severity findings.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from zohokit.core.context import RunContext
from zohokit.core.findings import Finding, Severity
from zohokit.modules.migration.mapping import load_mapping
from zohokit.modules.migration.metadata import metadata_from_dir
from zohokit.modules.migration.owners import users_from_file
from zohokit.modules.migration.preflight import ExtraChecks, SourceSpec, run_preflight
from zohokit.modules.migration.target_dedupe import target_fingerprint

ROOT = Path(__file__).resolve().parent.parent.parent.parent
MARIGOLD = ROOT / "fixtures" / "migration" / "marigold"

ERROR = Severity.ERROR


def _search_from_snapshot(payload: dict[str, object]):  # type: ignore[no-untyped-def]
    """Offline target search: email -> fingerprints from target_existing.json."""
    contacts = payload.get("Contacts", [])
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

    return search


def _report():  # type: ignore[no-untyped-def]
    doc = load_mapping(MARIGOLD / "mapping.yaml")
    sources = {
        entity.name: SourceSpec(
            path=str(MARIGOLD / "source" / f"{entity.source_kind}.csv"),
            kind=entity.source_kind,
        )
        for entity in doc.entities
    }
    metadata = metadata_from_dir(MARIGOLD / "fields")
    users = users_from_file(MARIGOLD / "users.json")
    snapshot = json.loads((MARIGOLD / "target_existing.json").read_text(encoding="utf-8"))
    extra = ExtraChecks(users=users, search=_search_from_snapshot(snapshot))
    return run_preflight(
        doc, sources, metadata, ctx=RunContext(now=datetime(2026, 1, 5, tzinfo=UTC)), extra=extra
    )


def finding_tuple(finding: Finding) -> tuple[str, str, str | None, int | None, str]:
    """Row-level identity: stable source key plus the physical file line.

    ``row_parse_error`` findings are positional by design (a parse fault
    has no record to key on), so their locator is the line; every other
    finding keys on the stable source record ID with the line alongside.
    """
    line = finding.evidence.get("line")
    assert line is None or isinstance(line, int)
    if finding.code == "row_parse_error":
        assert finding.entity_id.startswith("line-")
        assert isinstance(line, int)
        return (finding.entity, finding.code, None, line, finding.severity.value)
    return (finding.entity, finding.code, finding.entity_id, line, finding.severity.value)


def expected_tuples() -> set[tuple[str, str, str | None, int | None, str]]:
    """Answer-key entries as comparable tuples."""
    payload = json.loads((MARIGOLD / "answer_key.json").read_text(encoding="utf-8"))
    return {
        (entry["entity"], entry["code"], entry["source_id"], entry["line"], entry["severity"])
        for entry in payload["expected"]
    }


def test_marigold_answer_key_exact() -> None:
    report = _report()
    detected = {finding_tuple(finding) for finding in report.findings}
    assert detected == expected_tuples()


def test_marigold_finding_ids_unique() -> None:
    """Invariant: every finding in the report carries a distinct ID.

    Baseline suppression and diff-reports key on finding IDs, so two rows
    sharing one external ID must still surface two findings (regression:
    the duplicated 9001 rows once shared one ID).
    """
    report = _report()
    ids = [finding.id for finding in report.findings]
    assert len(set(ids)) == len(ids)


#: Codes the answer key allows at error severity (everything else is a regression).
EXPECTED_ERROR_CODES = frozenset(
    {
        "row_parse_error",
        "unknown_target_field",
        "read_only_target_field",
        "missing_source_column",
        "type_incompatible",
        "value_too_long",
        "picklist_value_missing",
        "mandatory_field_unmapped",
        "unique_field_collision_in_batch",
        "inactive_owner",
        "owner_unmapped",
        "unmapped_stage",
    }
)


def test_marigold_no_unexpected_errors() -> None:
    report = _report()
    unexpected = [
        finding
        for finding in report.findings
        if finding.severity is ERROR and finding.code not in EXPECTED_ERROR_CODES
    ]
    assert unexpected == []
    # The blank-line row_parse_error is a warning, so exactly one expected
    # entry is not an error.
    errors = sum(
        1 for entry in expected_tuples() if entry[4] == "error" and entry[1] in EXPECTED_ERROR_CODES
    )
    assert report.summary.error == errors == 22


def test_marigold_would_duplicate_fingerprinted() -> None:
    report = _report()
    matches = [f for f in report.findings if f.code == "would_duplicate_existing"]
    assert len(matches) == 1
    assert matches[0].entity_id == "71"
    assert matches[0].evidence["line"] == 73
    assert matches[0].evidence["target_fingerprint"].startswith("sha256:")
    assert "returning@example.invalid" not in str(matches[0].evidence)
