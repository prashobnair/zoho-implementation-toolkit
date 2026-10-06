"""In-source duplicate cluster tests + KI-001 shuffle invariance (TK-MIG-F4)."""

from __future__ import annotations

import random

from hypothesis import given, settings
from hypothesis import strategies as st

from zohokit.modules.migration.dedupe import (
    cluster_findings,
    cluster_signals,
    normalize_email_cell,
    normalize_phone_cell,
    parse_created_cell,
    signal_row,
)

EMAIL_COLS = ["Email"]
PHONE_COLS = ["Phone"]
COMPANY_COLS = ["Name"]
CREATED_COLS = ["Created", "Create Date"]


def _sig(row: dict[str, str]) -> object:
    return signal_row(
        row,
        id_col="ID",
        email_cols=EMAIL_COLS,
        phone_cols=PHONE_COLS,
        company_cols=COMPANY_COLS,
        created_cols=CREATED_COLS,
        default_region="IN",
    )


def test_email_cluster_survivor_is_earliest_then_smallest_id() -> None:
    rows = [
        {"ID": "p-9", "Email": "SAME@example.invalid", "Created": "2026-01-06"},
        {"ID": "p-2", "Email": "same@example.invalid", "Created": "2026-01-05"},
        {"ID": "p-1", "Email": "other@example.invalid", "Created": "2026-01-01"},
    ]
    clusters = cluster_signals([_sig(row) for row in rows])
    assert len(clusters) == 1
    assert clusters[0].members == ("p-2", "p-9")
    assert clusters[0].survivor == "p-2"
    assert clusters[0].signals == ("email",)
    findings = cluster_findings("people", clusters)
    assert len(findings) == 1
    assert findings[0].code == "fuzzy_duplicate_cluster"
    assert findings[0].entity_id == "p-2"
    assert findings[0].evidence["members"] == ["p-2", "p-9"]


def test_phone_cluster_without_region_code() -> None:
    rows = [
        {"ID": "a", "Phone": "9820000001", "Created": "2026-01-02"},
        {"ID": "b", "Phone": "+919820000001", "Created": "2026-01-01"},
    ]
    clusters = cluster_signals([_sig(row) for row in rows])
    assert len(clusters) == 1
    assert clusters[0].signals == ("phone",)
    assert clusters[0].survivor == "b"


def test_fuzzy_company_cluster_and_threshold() -> None:
    rows = [
        {"ID": "c-1", "Name": "Marigold Labs Private Limited", "Created": "2026-01-01"},
        {"ID": "c-2", "Name": "Marigold Labs Private Ltd", "Created": "2026-01-02"},
        {"ID": "c-3", "Name": "Northwind Traders", "Created": "2026-01-01"},
    ]
    clusters = cluster_signals([_sig(row) for row in rows])
    assert len(clusters) == 1
    assert clusters[0].members == ("c-1", "c-2")
    assert clusters[0].signals == ("company",)
    assert clusters[0].survivor == "c-1"


def test_invalid_cells_never_cluster() -> None:
    assert normalize_email_cell("not-an-email") is None
    assert normalize_phone_cell("zzz", default_region="IN") is None
    assert parse_created_cell("someday") == ""
    rows = [
        {"ID": "x", "Email": "not-an-email", "Phone": "zzz"},
        {"ID": "y", "Email": "also bad", "Phone": "???"},
    ]
    assert cluster_signals([_sig(row) for row in rows]) == []


def _ids_and_survivors(rows: list[dict[str, str]]) -> tuple[list[str], list[str]]:
    clusters = cluster_signals([_sig(row) for row in rows])
    findings = cluster_findings("people", clusters)
    return sorted(item.id for item in findings), sorted(
        str(item.evidence["survivor"]) for item in findings
    )


def test_shuffled_input_changes_nothing() -> None:
    rows = [
        {"ID": "p-1", "Email": "a@example.invalid", "Phone": "+919000000001"},
        {"ID": "p-2", "Email": "A@example.invalid", "Phone": "+918000000002"},
        {"ID": "p-3", "Email": "b@example.invalid", "Phone": "+919000000001"},
        {"ID": "p-4", "Email": "c@example.invalid", "Phone": "+917000000004"},
    ]
    expected = _ids_and_survivors(rows)
    rng = random.Random(42)
    for _ in range(10):
        shuffled = list(rows)
        rng.shuffle(shuffled)
        assert _ids_and_survivors(shuffled) == expected


ROW_STRATEGY = st.lists(
    st.fixed_dictionaries(
        {
            "ID": st.sampled_from(["k-1", "k-2", "k-3", "k-4"]),
            "Email": st.sampled_from(
                ["a@example.invalid", "A@example.invalid", "b@example.invalid", ""]
            ),
            "Created": st.sampled_from(["2026-01-01", "2026-01-02", ""]),
        }
    ),
    min_size=2,
    max_size=6,
)


@given(rows=ROW_STRATEGY)
@settings(max_examples=60)
def test_shuffle_invariance_property(rows: list[dict[str, str]]) -> None:
    """KI-001: shuffling input rows changes no finding ID or survivor."""
    expected = _ids_and_survivors(rows)
    rng = random.Random(len(rows))
    shuffled = list(rows)
    rng.shuffle(shuffled)
    assert _ids_and_survivors(shuffled) == expected
