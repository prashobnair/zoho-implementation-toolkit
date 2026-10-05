"""Metadata validation replayed over the real recorded cassettes (TK-MIG-F3).

Reads ``cassettes/crm/fields_{Leads,Contacts,Deals}.json`` (owner-approved
redacted verification run) through the same envelope loader the offline
CLI uses. No network: plain file reads, safe under
``pytest -m contract --disable-socket``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zohokit.modules.migration.mapping import MappingDoc
from zohokit.modules.migration.metadata import (
    TargetMetadata,
    metadata_from_cassette_envelope,
    metadata_from_dir,
    validate_entity,
)

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parent.parent.parent
CASSETTES = ROOT / "cassettes" / "crm"


def _metadata() -> TargetMetadata:
    modules = {}
    for module in ("Contacts", "Deals"):
        payload = json.loads((CASSETTES / f"fields_{module}.json").read_text(encoding="utf-8"))
        modules[module] = metadata_from_cassette_envelope(payload)
    return TargetMetadata(modules=modules)


def _doc(fields: dict[str, dict[str, object]]) -> MappingDoc:
    return MappingDoc.model_validate(
        {
            "version": 1,
            "entities": [
                {
                    "name": "deals",
                    "source_kind": "deals",
                    "target_module": "Deals",
                    "fields": fields,
                }
            ],
        }
    )


def _lined(rows: list[dict[str, str]], start: int = 2) -> list[tuple[int, dict[str, str]]]:
    """Pair rows with physical file lines (header is line 1)."""
    return [(start + index, row) for index, row in enumerate(rows)]


def test_real_stage_picklist_accepts_and_rejects() -> None:
    metadata = _metadata()
    fields = metadata.fields_for("Deals")
    assert "Qualification" in fields["Stage"].pick_list_values
    assert fields["Stage"].system_mandatory is True
    entity = _doc({"Deal_Name": {"from": "Title"}, "Stage": {"from": "Stage"}}).entities[0]
    header = ["Title", "Stage"]
    ok = validate_entity(
        entity, fields, header, _lined([{"Title": "Pilot", "Stage": "Qualification"}])
    )
    assert [item.code for item in ok] == []
    bad = validate_entity(entity, fields, header, _lined([{"Title": "Pilot", "Stage": "Bogus"}]))
    assert [item.code for item in bad] == ["picklist_value_missing"]


def test_real_cassette_codes() -> None:
    metadata = _metadata()
    fields = metadata.fields_for("Deals")
    header = ["Title", "Stage"]
    rows = [{"Title": "Pilot", "Stage": "Qualification"}]
    # Unknown + read-only + mandatory gap + lookup without resolution.
    entity = _doc(
        {
            "Deal_Name": {"from": "Title"},
            "Nope__s": {"from": "Title"},
            "id": {"from": "Title"},
            "Account_Name": {"from": "Org"},
        }
    ).entities[0]
    codes = sorted(
        item.code
        for item in validate_entity(
            entity, fields, [*header, "Org"], _lined([{**rows[0], "Org": "Acme"}])
        )
    )
    # Mapping deal text into the bigint `id` is also a genuine type error.
    assert codes == [
        "lookup_unresolvable",
        "mandatory_field_unmapped",
        "read_only_target_field",
        "type_incompatible",
        "unknown_target_field",
    ]
    # A 121-char deal name exceeds the recorded length 120 with its max.
    long_entity = _doc({"Deal_Name": {"from": "Title"}, "Stage": {"from": "Stage"}}).entities[0]
    long = validate_entity(
        long_entity, fields, header, _lined([{"Title": "D" * 121, "Stage": "Qualification"}])
    )
    assert [(item.code, item.evidence["max"]) for item in long] == [("value_too_long", 120)]


def test_contacts_mandatory_last_name_from_cassette() -> None:
    metadata = _metadata()
    fields = metadata.fields_for("Contacts")
    assert fields["Last_Name"].system_mandatory is True
    assert fields["Last_Name"].length == 80
    entity = MappingDoc.model_validate(
        {
            "version": 1,
            "entities": [
                {
                    "name": "people",
                    "source_kind": "persons",
                    "target_module": "Contacts",
                    "fields": {"Email": {"from": "Email"}},
                }
            ],
        }
    ).entities[0]
    findings = validate_entity(entity, fields, ["Email"], _lined([{"Email": "a@example.invalid"}]))
    assert [(item.code, item.entity_id) for item in findings] == [
        ("mandatory_field_unmapped", "Last_Name")
    ]
    # Duplicate emails collide in the batch (fingerprints only).
    dup = MappingDoc.model_validate(
        {
            "version": 1,
            "entities": [
                {
                    "name": "people",
                    "source_kind": "persons",
                    "target_module": "Contacts",
                    "fields": {"Last_Name": {"from": "N"}, "Email": {"from": "E"}},
                }
            ],
        }
    ).entities[0]
    collisions = validate_entity(
        dup,
        fields,
        ["N", "E"],
        _lined(
            [
                {"N": "a", "E": "dup@example.invalid"},
                {"N": "b", "E": "dup@example.invalid"},
            ]
        ),
    )
    # No ID column exists, so keys fall back to content hashes (never positions).
    assert len(collisions) == 2
    assert all(item.entity_id.startswith("hash:") for item in collisions)
    assert sorted(item.evidence["line"] for item in collisions) == [2, 3]
    assert all(item.code == "unique_field_collision_in_batch" for item in collisions)


def test_metadata_from_dir_reads_cassette_envelopes(tmp_path: Path) -> None:
    target = tmp_path / "fields"
    target.mkdir()
    for name in ("fields_Contacts.json", "fields_Deals.json"):
        (target / name).write_bytes((CASSETTES / name).read_bytes())
    metadata = metadata_from_dir(target)
    assert sorted(metadata.modules) == ["Contacts", "Deals"]
    assert "Stage" in metadata.fields_for("Deals")
