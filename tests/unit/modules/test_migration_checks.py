"""Target dedupe, stage, owner and history check tests (TK-MIG-F5..F8)."""

from __future__ import annotations

from zohokit.modules.migration.history import check_history
from zohokit.modules.migration.mapping import MappingDoc
from zohokit.modules.migration.metadata import FieldMeta
from zohokit.modules.migration.owners import check_owners, users_from_envelope
from zohokit.modules.migration.stages import check_stages
from zohokit.modules.migration.target_dedupe import (
    check_against_target,
    coverage_finding,
    target_fingerprint,
)


def _doc(payload: dict[str, object]) -> MappingDoc:
    return MappingDoc.model_validate(payload)


def test_target_search_fingerprints_and_review() -> None:
    seen: list[tuple[str, str | None, str | None]] = []

    def search(module: str, email: str | None, phone: str | None) -> list[str]:
        seen.append((module, email, phone))
        if email == "dup@example.invalid":
            return [target_fingerprint("1455423000000476001")]
        return []

    candidates = [
        ("p-1", 2, "dup@example.invalid", None),
        ("p-2", 3, None, "+919000000002"),
        ("p-3", 4, None, None),
    ]
    findings, checked, total, truncated = check_against_target(
        "people", "Contacts", candidates, search
    )
    assert [(item.entity_id, item.code) for item in findings] == [
        ("p-1", "would_duplicate_existing")
    ]
    assert findings[0].severity == "review"
    assert findings[0].evidence["matched_on"] == "email"
    assert findings[0].evidence["line"] == 2
    assert findings[0].evidence["target_fingerprint"].startswith("sha256:")
    assert "1455423000000476001" not in str(findings[0].evidence)
    assert (checked, total, truncated) == (2, 3, False)
    assert seen == [
        ("Contacts", "dup@example.invalid", None),
        ("Contacts", None, "+919000000002"),
    ]


def test_target_search_email_first_and_budget_truncation() -> None:
    calls: list[str | None] = []

    def search(module: str, email: str | None, phone: str | None) -> list[str]:
        calls.append(email or phone)
        return []

    candidates = [
        ("p-1", 2, None, "+919000000001"),
        ("p-2", 3, "b@example.invalid", None),
        ("p-3", 4, "c@example.invalid", None),
    ]
    ordered = sorted(candidates, key=lambda item: (item[2] is None, item[3] is None, item[0]))
    findings, checked, total, truncated = check_against_target(
        "people", "Contacts", ordered, search, budget=1
    )
    assert calls == ["b@example.invalid"]
    assert (checked, total, truncated) == (1, 3, True)
    assert findings == []
    coverage = coverage_finding("people", checked=checked, total=total, truncated=truncated)
    assert coverage.severity == "info"
    assert coverage.evidence == {"checked": 1, "total": 3, "truncated": True}
    assert coverage.message == "Target duplicate search checked 1 / 3 rows."


STAGE_META = FieldMeta(
    api_name="Stage",
    data_type="picklist",
    length=120,
    pick_list_values=("Qualification", "Closed Won"),
    system_mandatory=True,
)


def test_stage_picklist_and_probability() -> None:
    doc = _doc(
        {
            "version": 1,
            "entities": [
                {
                    "name": "deals",
                    "source_kind": "deals",
                    "target_module": "Deals",
                    "fields": {
                        "Deal_Name": {"from": "Title"},
                        "Stage": {"from": "Stage"},
                        "Probability": {"from": "Prob"},
                    },
                    "stage_probabilities": {"Qualification": 10.0},
                }
            ],
        }
    )
    entity = doc.entities[0]
    header = ["Title", "Stage", "Prob"]
    rows = [
        ("d-1", 2, {"Title": "A", "Stage": "Qualification", "Prob": "10"}),
        ("d-2", 3, {"Title": "B", "Stage": "Bogus", "Prob": "50"}),
        ("d-3", 4, {"Title": "C", "Stage": "Qualification", "Prob": "80"}),
    ]
    findings = check_stages(entity, rows, header, STAGE_META)
    assert [(item.entity_id, item.code) for item in findings] == [
        ("d-2", "unmapped_stage"),
        ("d-3", "stage_probability_mismatch"),
    ]
    assert findings[0].severity == "error"
    assert findings[1].severity == "warning"
    assert findings[0].evidence["line"] == 3
    assert findings[1].evidence == {
        "stage": "Qualification",
        "expected": 10.0,
        "actual": 80.0,
        "line": 4,
    }


def test_owners_redacted_and_statuses() -> None:
    users = users_from_envelope(
        {
            "users": [
                {"email": "Active@Example.Invalid", "status": "active"},
                {"email": "gone@example.invalid", "status": "inactive"},
            ]
        }
    )
    assert users == {"active@example.invalid": "active", "gone@example.invalid": "inactive"}
    doc = _doc(
        {
            "version": 1,
            "entities": [
                {
                    "name": "people",
                    "source_kind": "persons",
                    "target_module": "Contacts",
                    "fields": {"Owner": {"from": "Owner Email"}},
                }
            ],
        }
    )
    entity = doc.entities[0]
    header = ["Owner Email"]
    rows = [
        ("p-1", 2, {"Owner Email": "active@example.invalid"}),
        ("p-2", 3, {"Owner Email": "gone@example.invalid"}),
        ("p-3", 4, {"Owner Email": "ghost@example.invalid"}),
        ("p-4", 5, {"Owner Email": ""}),
    ]
    findings = check_owners(entity, rows, header, users)
    assert [(item.entity_id, item.code) for item in findings] == [
        ("p-2", "inactive_owner"),
        ("p-3", "owner_unmapped"),
    ]
    assert all(item.severity == "error" for item in findings)
    assert findings[0].evidence == {"owner": "g***@example.invalid", "line": 3}
    assert findings[1].evidence == {"owner": "g***@example.invalid", "line": 4}
    assert "ghost@example.invalid" not in str(findings)


def test_history_unsupported_and_counts() -> None:
    doc = _doc(
        {
            "version": 1,
            "entities": [
                {
                    "name": "activities",
                    "source_kind": "activities",
                    "target_module": "Calls",
                    "fields": {"Subject": {"from": "Subject"}},
                    "lookups": {"Call_For": {"entity": "deals", "via": "Deal ID"}},
                    "history": {"type_col": "Type", "supported": ["Call", "Meeting"]},
                }
            ],
        }
    )
    entity = doc.entities[0]
    header = ["Subject", "Type", "Deal ID"]
    rows = [
        ("a-1", 2, {"Subject": "Kickoff", "Type": "Call", "Deal ID": "100"}),
        ("a-2", 3, {"Subject": "Old fax", "Type": "Fax", "Deal ID": "100"}),
        ("a-3", 4, {"Subject": "Sync", "Type": "Meeting", "Deal ID": "101"}),
    ]
    findings = check_history(entity, rows, header)
    assert [(item.entity_id, item.code, item.severity) for item in findings] == [
        ("a-2", "history_type_unsupported", "warning"),
        ("counts", "history_type_unsupported", "info"),
    ]
    assert findings[0].evidence["history_type"] == "Fax"
    assert findings[0].evidence["line"] == 3
    assert findings[1].evidence == {"counts": {"100": 2, "101": 1}, "total": 3}
