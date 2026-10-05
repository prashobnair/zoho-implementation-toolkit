"""Metadata validation tests: one fixture per TK-MIG-F3 code."""

from __future__ import annotations

from zohokit.modules.migration.mapping import MappingDoc
from zohokit.modules.migration.metadata import (
    FieldMeta,
    TargetMetadata,
    disambiguated_record_keys,
    stable_record_key,
    validate_entity,
    validate_mapping,
)

FIELDS: dict[str, FieldMeta] = {
    "Last_Name": FieldMeta(
        api_name="Last_Name", data_type="text", length=80, system_mandatory=True
    ),
    "Email": FieldMeta(api_name="Email", data_type="email", length=100),
    "Phone": FieldMeta(api_name="Phone", data_type="phone", length=30),
    "Stage": FieldMeta(
        api_name="Stage",
        data_type="picklist",
        length=120,
        pick_list_values=("Qualification", "Closed Won"),
        system_mandatory=True,
    ),
    "Amount": FieldMeta(api_name="Amount", data_type="currency", length=16),
    "Closing_Date": FieldMeta(api_name="Closing_Date", data_type="date", length=20),
    "Account_Name": FieldMeta(api_name="Account_Name", data_type="lookup", length=120),
    "External_ID__s": FieldMeta(
        api_name="External_ID__s", data_type="text", length=50, unique=True
    ),
    "id": FieldMeta(api_name="id", data_type="bigint", length=18, read_only=True),
}

META = TargetMetadata(modules={"Contacts": FIELDS})


def _doc(fields: dict[str, dict[str, object]], **extra: object) -> MappingDoc:
    payload: dict[str, object] = {
        "version": 1,
        "entities": [
            {
                "name": "people",
                "source_kind": "persons",
                "target_module": "Contacts",
                "fields": fields,
                **extra,
            }
        ],
    }
    return MappingDoc.model_validate(payload)


def _lined(rows: list[dict[str, str]], start: int = 2) -> list[tuple[int, dict[str, str]]]:
    """Pair rows with physical file lines (header is line 1)."""
    return [(start + index, row) for index, row in enumerate(rows)]


def _codes(doc: MappingDoc, rows: list[dict[str, str]], header: list[str]) -> list[str]:
    entity = doc.entities[0]
    return sorted(finding.code for finding in validate_entity(entity, FIELDS, header, _lined(rows)))


def test_clean_mapping_has_no_findings() -> None:
    doc = _doc(
        {
            "Last_Name": {"from": "Name"},
            "Email": {"from": "Email"},
            "Stage": {"from": "Stage"},
            "External_ID__s": {"from": "ID"},
        }
    )
    rows = [
        {"Name": "Aarav", "Email": "aarav@example.invalid", "Stage": "Qualification", "ID": "1"}
    ]
    assert _codes(doc, rows, ["Name", "Email", "Stage", "ID"]) == []


def test_unknown_target_field() -> None:
    doc = _doc({"Nope__s": {"from": "Name"}, "Last_Name": {"from": "Name"}})
    findings = validate_entity(doc.entities[0], FIELDS, ["Name"], _lined([{"Name": "x"}]))
    assert [
        (item.code, item.entity_id) for item in findings if item.code == "unknown_target_field"
    ] == [("unknown_target_field", "Nope__s")]
    assert all(item.severity == "error" for item in findings)


def test_read_only_target_field() -> None:
    doc = _doc({"id": {"from": "ID"}, "Last_Name": {"from": "Name"}, "Stage": {"from": "S"}})
    rows = [{"ID": "1", "Name": "x", "S": "Qualification"}]
    assert _codes(doc, rows, ["ID", "Name", "S"]) == ["read_only_target_field"]


def test_type_incompatible_email_and_date() -> None:
    doc = _doc(
        {
            "Last_Name": {"from": "Name"},
            "Email": {"from": "Email"},
            "Closing_Date": {"from": "Close"},
            "Stage": {"from": "S"},
        }
    )
    rows = [{"Name": "x", "Email": "not-an-email", "Close": "2026-01-31", "S": "Qualification"}]
    assert _codes(doc, rows, ["Name", "Email", "Close", "S"]) == ["type_incompatible"]


def test_value_too_long_carries_max() -> None:
    doc = _doc({"Last_Name": {"from": "Name"}, "Stage": {"from": "S"}})
    rows = [{"Name": "N" * 81, "S": "Qualification"}]
    findings = validate_entity(doc.entities[0], FIELDS, ["Name", "S"], _lined(rows))
    long = [item for item in findings if item.code == "value_too_long"]
    assert len(long) == 1
    assert long[0].evidence["max"] == 80
    assert long[0].evidence["actual_length"] == 81


def test_picklist_value_missing() -> None:
    doc = _doc({"Last_Name": {"from": "Name"}, "Stage": {"from": "Stage"}})
    rows = [{"Name": "x", "Stage": "Bogus"}]
    findings = validate_entity(doc.entities[0], FIELDS, ["Name", "Stage"], _lined(rows))
    missing = [item for item in findings if item.code == "picklist_value_missing"]
    assert len(missing) == 1
    assert missing[0].evidence["allowed_count"] == 2
    # A mapped value passes silently.
    assert _codes(doc, [{"Name": "x", "Stage": "Closed Won"}], ["Name", "Stage"]) == []


def test_mandatory_field_unmapped() -> None:
    doc = _doc({"Email": {"from": "Email"}})
    findings = validate_entity(
        doc.entities[0], FIELDS, ["Email"], _lined([{"Email": "a@example.invalid"}])
    )
    assert sorted((item.code, item.entity_id) for item in findings) == [
        ("mandatory_field_unmapped", "Last_Name"),
        ("mandatory_field_unmapped", "Stage"),
    ]


def test_lookup_unresolvable() -> None:
    doc = _doc(
        {"Last_Name": {"from": "Name"}, "Account_Name": {"from": "Org"}, "Stage": {"from": "S"}}
    )
    rows = [{"Name": "x", "Org": "Acme", "S": "Qualification"}]
    findings = validate_entity(doc.entities[0], FIELDS, ["Name", "Org", "S"], _lined(rows))
    assert [item.code for item in findings] == ["lookup_unresolvable"]
    assert findings[0].severity == "review"
    # A lookups entry resolves it.
    resolved = _doc(
        {"Last_Name": {"from": "Name"}, "Account_Name": {"from": "Org"}, "Stage": {"from": "S"}},
        lookups={"Account_Name": {"entity": "companies", "via": "Org"}},
    )
    assert _codes(resolved, rows, ["Name", "Org", "S"]) == []


def test_unique_field_collision_in_batch_uses_fingerprints() -> None:
    doc = _doc({"Last_Name": {"from": "Name"}, "Email": {"from": "Email"}, "Stage": {"from": "S"}})
    rows = [
        {"Name": "a", "Email": "same@example.invalid", "S": "Qualification"},
        {"Name": "b", "Email": "SAME@example.invalid", "S": "Qualification"},
    ]
    findings = validate_entity(doc.entities[0], FIELDS, ["Name", "Email", "S"], _lined(rows))
    collisions = [item for item in findings if item.code == "unique_field_collision_in_batch"]
    assert len(collisions) == 2
    # No ID column exists, so keys fall back to content hashes (never positions).
    assert all(item.entity_id.startswith("hash:") for item in collisions)
    assert len({item.entity_id for item in collisions}) == 2
    assert sorted(item.evidence["line"] for item in collisions) == [2, 3]
    assert all("value_fingerprint" in item.evidence for item in collisions)
    assert all("same@example.invalid" not in str(item.evidence) for item in collisions)


def test_per_record_findings_use_stable_source_key_and_line() -> None:
    doc = _doc(
        {
            "Last_Name": {"from": "Name"},
            "Email": {"from": "Email"},
            "Stage": {"from": "S"},
            "External_ID__s": {"from": "ID"},
        },
        external_id={"field": "External_ID__s", "from": "ID"},
    )
    entity = doc.entities[0]
    header = ["ID", "Name", "Email", "S"]
    rows = [
        {"ID": "41", "Name": "x", "Email": "not-an-email", "S": "Qualification"},
        {"ID": "42", "Name": "N" * 81, "Email": "ok@example.invalid", "S": "Qualification"},
    ]
    findings = validate_entity(entity, FIELDS, header, _lined(rows, start=10))
    by_id = {item.entity_id: item for item in findings}
    assert set(by_id) == {"41", "42"}
    assert by_id["41"].code == "type_incompatible"
    assert by_id["41"].evidence["line"] == 10
    assert by_id["42"].code == "value_too_long"
    assert by_id["42"].evidence["line"] == 11
    assert stable_record_key(entity, header, rows[0]) == "41"


def test_stable_ids_survive_prepend_and_shuffle() -> None:
    doc = _doc(
        {
            "Last_Name": {"from": "Name"},
            "Email": {"from": "Email"},
            "Stage": {"from": "S"},
        },
        external_id={"field": "External_ID__s", "from": "ID"},
    )
    entity = doc.entities[0]
    header = ["ID", "Name", "Email", "S"]
    base = [
        {"ID": "41", "Name": "x", "Email": "not-an-email", "S": "Qualification"},
        {"ID": "42", "Name": "y", "Email": "ok@example.invalid", "S": "Bogus"},
    ]
    before = validate_entity(entity, FIELDS, header, _lined(base, start=2))
    before_ids = sorted(item.id for item in before)
    assert len(set(before_ids)) == len(before_ids)  # Invariant: no finding-ID collision.
    # Prepending a valid row shifts physical lines but changes no finding ID.
    prepended = [{"ID": "99", "Name": "z", "Email": "z@example.invalid", "S": "Qualification"}]
    after = validate_entity(entity, FIELDS, header, _lined(prepended + base, start=2))
    after_ids = sorted(item.id for item in after if item.entity_id in {"41", "42"})
    assert after_ids == before_ids
    assert len({item.id for item in after}) == len(after)
    # Shuffling the rows changes no finding ID.
    shuffled = validate_entity(entity, FIELDS, header, _lined(list(reversed(base)), start=2))
    assert sorted(item.id for item in shuffled) == before_ids
    assert len({item.id for item in shuffled}) == len(shuffled)


def test_duplicate_source_ids_get_distinct_stable_keys() -> None:
    doc = _doc(
        {
            "Last_Name": {"from": "Name"},
            "Email": {"from": "Email"},
            "Stage": {"from": "S"},
        },
        external_id={"field": "External_ID__s", "from": "ID"},
    )
    entity = doc.entities[0]
    header = ["ID", "Name", "Email", "S"]
    dup_a = {"ID": "9001", "Name": "Diya", "Email": "diya@example.invalid", "S": "Qualification"}
    dup_b = {"ID": "9001", "Name": "Riya", "Email": "riya@example.invalid", "S": "Qualification"}
    solo = {"ID": "41", "Name": "x", "Email": "x@example.invalid", "S": "Qualification"}
    rows = [dup_a, dup_b, solo]
    keys = disambiguated_record_keys(entity, header, _lined(rows))
    assert keys[0] != keys[1]
    assert keys[0].startswith("9001#") and keys[1].startswith("9001#")
    # Unique keys are unchanged, so existing finding IDs stay stable.
    assert keys[2] == "41"
    assert stable_record_key(entity, header, dup_a) == "9001"
    # Reordering the batch changes no key; inserting another row neither.
    assert sorted(disambiguated_record_keys(entity, header, _lined(list(reversed(rows))))) == (
        sorted(keys)
    )
    fresh = {"ID": "99", "Name": "z", "Email": "z@example.invalid", "S": "Qualification"}
    assert disambiguated_record_keys(entity, header, _lined([fresh, *rows]))[1:] == keys


def test_duplicate_source_ids_yield_distinct_collision_findings() -> None:
    doc = _doc(
        {"Last_Name": {"from": "Name"}, "Email": {"from": "Email"}, "Stage": {"from": "S"}},
        external_id={"field": "External_ID__s", "from": "ID"},
    )
    entity = doc.entities[0]
    header = ["ID", "Name", "Email", "S"]
    rows = [
        {"ID": "9001", "Name": "Diya", "Email": "same@example.invalid", "S": "Qualification"},
        {"ID": "9001", "Name": "Riya", "Email": "SAME@example.invalid", "S": "Qualification"},
    ]
    findings = validate_entity(entity, FIELDS, header, _lined(rows))
    collisions = [item for item in findings if item.code == "unique_field_collision_in_batch"]
    assert len(collisions) == 2
    assert len({item.entity_id for item in collisions}) == 2
    assert all(item.entity_id.startswith("9001#") for item in collisions)
    # Invariant: distinct findings carry distinct finding IDs.
    assert len({item.id for item in collisions}) == 2
    assert len({item.id for item in findings}) == len(findings)


def test_content_hash_fallback_when_no_id_column() -> None:
    doc = _doc({"Last_Name": {"from": "Name"}, "Stage": {"from": "S"}})
    entity = doc.entities[0]
    header = ["Name", "S"]
    row = {"Name": "N" * 81, "S": "Qualification"}
    findings = validate_entity(entity, FIELDS, header, _lined([row], start=5))
    assert len(findings) == 1
    assert findings[0].entity_id.startswith("hash:")
    assert findings[0].evidence["line"] == 5


def test_missing_source_column() -> None:
    doc = _doc({"Last_Name": {"from": "Ghost"}, "Stage": {"from": "S"}})
    rows = [{"Name": "x", "S": "Qualification"}]
    assert _codes(doc, rows, ["Name", "S"]) == ["missing_source_column"]
    # The transform failure also surfaces as type-incompatible per row.
    doc2 = _doc(
        {
            "Last_Name": {"from": "Name"},
            "Stage": {"from": "S"},
            "Phone": {"from": "Phone", "transform": [{"name": "e164", "args": {}}]},
        }
    )
    assert _codes(
        doc2, [{"Name": "x", "S": "Qualification", "Phone": "zzz"}], ["Name", "S", "Phone"]
    ) == ["type_incompatible"]


def test_unknown_module_degrades_to_review() -> None:
    doc = _doc({"Last_Name": {"from": "Name"}})
    findings = validate_mapping(
        doc, TargetMetadata(modules={}), {"people": ["Name"]}, {"people": []}
    )
    assert [item.code for item in findings] == ["unknown_target_field"]
    assert findings[0].severity == "review"
