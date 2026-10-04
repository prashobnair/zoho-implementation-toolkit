"""Mapping DSL tests: transforms, line-numbered config errors (TK-MIG-F1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from zohokit.modules.migration.mapping import (
    KNOWN_TRANSFORMS,
    MappingConfigError,
    TransformError,
    apply_transforms,
    coerce_transform,
    load_mapping,
)

ROOT = Path(__file__).resolve().parent.parent.parent.parent


def test_fixture_mapping_loads() -> None:
    doc = load_mapping(ROOT / "fixtures" / "migration" / "mapping.yaml")
    assert doc.version == 1
    assert [entity.name for entity in doc.entities] == ["people", "companies", "deals"]
    people = doc.entities[0]
    assert people.target_module == "Contacts"
    assert people.fields["Email"].from_col == "Email"
    assert [spec.name for spec in people.fields["Phone"].transform] == ["trim", "e164"]
    assert people.external_id is not None and people.external_id.field == "External_ID__s"


def test_each_transform_applies() -> None:
    row = {
        "Name": "  Aarav  ",
        "Phone": "+919000000001",
        "Close": "31/01/2026",
        "Value": "250000",
        "Currency": "INR",
        "First": "Aarav",
        "Last": "Sharma",
    }
    assert apply_transforms("  Aarav  ", row, [coerce_transform("trim")]) == "Aarav"
    assert apply_transforms("AARAV", row, [coerce_transform("casefold")]) == "aarav"
    assert (
        apply_transforms("9820000001", row, [coerce_transform("e164(region=IN)")])
        == "+919820000001"
    )
    assert (
        apply_transforms("31/01/2026", row, [coerce_transform('date(format="%d/%m/%Y")')])
        == "2026-01-31"
    )
    assert (
        apply_transforms("250000", row, [coerce_transform("money(currency_col=Currency)")])
        == "250000"
    )
    assert (
        apply_transforms("web", row, [coerce_transform({"map": {"values": {"web": "Web"}}})])
        == "Web"
    )
    assert (
        apply_transforms(
            None, row, [coerce_transform({"concat": {"fields": ["First", "Last"], "sep": " "}})]
        )
        == "Aarav Sharma"
    )


def test_money_uses_core_parser() -> None:
    with pytest.raises(TransformError):
        apply_transforms(
            "1.234", {"Currency": "INR"}, [coerce_transform("money(currency_col=Currency)")]
        )
    with pytest.raises(TransformError):
        apply_transforms(
            "10", {"Currency": "XX"}, [coerce_transform("money(currency_col=Currency)")]
        )
    with pytest.raises(TransformError):
        apply_transforms("nope", {}, [coerce_transform("e164(region=IN)")])
    with pytest.raises(TransformError):
        apply_transforms("zzz", {}, [coerce_transform({"map": {"values": {"a": "b"}}})])


def test_missing_values_pass_through() -> None:
    specs = [coerce_transform("trim"), coerce_transform("e164(region=IN)")]
    assert apply_transforms(None, {}, specs) is None
    assert apply_transforms("", {}, specs) == ""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "mapping.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_invalid_transform_reports_line_number(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "version: 1\n"
        "source: generic\n"
        "entities:\n"
        "  - name: people\n"
        "    source_kind: persons\n"
        "    target_module: Contacts\n"
        "    fields:\n"
        "      Last_Name: {from: Name, transform: [trim, frobnicate]}\n",
    )
    with pytest.raises(MappingConfigError) as excinfo:
        load_mapping(path)
    expected = (
        f"{path}:8: transform frobnicate failed: unknown transform "
        f"(expected one of {list(KNOWN_TRANSFORMS)})"
    )
    assert str(excinfo.value) == expected


def test_bad_transform_args_report_line_number(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "version: 1\n"
        "entities:\n"
        "  - name: people\n"
        "    source_kind: persons\n"
        "    target_module: Contacts\n"
        "    fields:\n"
        '      Amount: {from: Value, transform: ["money"]}\n',
    )
    with pytest.raises(MappingConfigError) as excinfo:
        load_mapping(path)
    assert str(excinfo.value).startswith(f"{path}:7: ")
    assert "currency_col" in str(excinfo.value)


def test_concat_requires_omitted_from(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "version: 1\n"
        "entities:\n"
        "  - name: people\n"
        "    source_kind: persons\n"
        "    target_module: Contacts\n"
        "    fields:\n"
        "      Last_Name: {from: Name, transform: [{concat: {fields: [A, B]}}]}\n",
    )
    with pytest.raises(MappingConfigError) as excinfo:
        load_mapping(path)
    assert "omit 'from'" in str(excinfo.value)


def test_schema_violation_reports_line_number(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "version: 1\nentities:\n  - name: people\n    target_module: Contacts\n    fields: {}\n",
    )
    with pytest.raises(MappingConfigError) as excinfo:
        load_mapping(path)
    # The missing source_kind line: the entity mapping starts at line 3.
    assert str(excinfo.value).startswith(f"{path}:")
    assert "invalid mapping" in str(excinfo.value)


def test_unknown_version_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "version: 2\nentities: []\n")
    with pytest.raises(MappingConfigError):
        load_mapping(path)
