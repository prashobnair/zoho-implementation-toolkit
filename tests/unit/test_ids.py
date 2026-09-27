"""Unit + property tests for stable identity (TK-CORE-2, TK-FIX-1)."""

from __future__ import annotations

from itertools import permutations
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from zohokit.core.ids import canonical_json, finding_id, fingerprint

json_values: st.SearchStrategy[Any] = st.recursive(
    st.integers() | st.text(max_size=8),
    lambda children: (
        st.lists(children, max_size=3) | st.dictionaries(st.text(max_size=4), children, max_size=3)
    ),
    max_leaves=6,
)


def test_finding_id_ignores_mutable_evidence() -> None:
    first = finding_id("migration", "orphan_person", "deals", "d-2")
    second = finding_id("migration", "orphan_person", "deals", "d-2")
    assert first == second
    assert len(first) == 24


def test_finding_id_changes_with_identity_parts() -> None:
    base = finding_id("migration", "orphan_person", "deals", "d-2")
    assert finding_id("migration", "orphan_person", "deals", "d-3") != base
    assert finding_id("migration", "orphan_person", "deals", "d-2", "extra") != base


def test_evidence_values_cannot_change_identity() -> None:
    """TK-CORE-2 acceptance: evidence is not an input to the identity function."""
    import inspect

    assert "evidence" not in inspect.signature(finding_id).parameters


def test_finding_id_exact_value() -> None:
    assert finding_id("migration", "orphan_person", "deals", "d-2") == "c0800b41f6fb8d7ead02b9a3"


def test_newline_parts_do_not_collide() -> None:
    """Regression: newline-joined parts collided; canonical JSON cannot."""
    assert finding_id("m", "c", "a\nb", "x") == "74c7dbced760e022159168dc"
    assert finding_id("m", "c", "a", "b\nx") == "43df888d072100cb426689cc"


def test_fingerprint_is_order_independent() -> None:
    components = [
        {"kind": "workflow", "name": "assign-owner"},
        {"kind": "field", "name": "External_Ref"},
        {"kind": "field", "name": "Amount"},
    ]
    expected = fingerprint(components)
    for ordering in permutations(components):
        assert fingerprint(list(ordering)) == expected


def test_fingerprint_detects_attribute_change() -> None:
    before = [{"kind": "field", "name": "Stage", "required": False}]
    after = [{"kind": "field", "name": "Stage", "required": True}]
    assert fingerprint(before) != fingerprint(after)


@given(json_values)
def test_canonical_json_is_deterministic(value: Any) -> None:
    assert canonical_json(value) == canonical_json(value)


@given(
    st.text(min_size=1, max_size=16),
    st.text(min_size=1, max_size=16),
    st.text(min_size=1, max_size=16),
    st.text(min_size=1, max_size=16),
    st.text(max_size=16),
)
def test_identity_is_stable_hex(
    module: str, code: str, entity: str, entity_id: str, discriminator: str
) -> None:
    """TK-CORE-2: the id depends only on identity parts (never mutable values)."""
    first = finding_id(module, code, entity, entity_id, discriminator)
    assert first == finding_id(module, code, entity, entity_id, discriminator)
    assert len(first) == 24
    assert all(char in "0123456789abcdef" for char in first)
