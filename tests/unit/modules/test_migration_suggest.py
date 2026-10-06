"""Suggester tests (AI-MIG-1/2): heuristic, validation, AI paths, renderers."""

from __future__ import annotations

import json
from pathlib import Path

from zohokit.ai.providers import FakeProvider
from zohokit.modules.migration.metadata import FieldMeta
from zohokit.modules.migration.suggest import (
    ColumnSamples,
    draft_yaml,
    guess_transform,
    heuristic_mapping,
    read_column_samples,
    render_mapping_html,
    render_mapping_table,
    render_transform_html,
    render_transform_table,
    suggest_mapping,
    suggest_transform,
    validate_mapping,
    validate_transform,
)


def _fields() -> dict[str, FieldMeta]:
    return {
        "First_Name": FieldMeta(api_name="First_Name", data_type="string"),
        "Email": FieldMeta(api_name="Email", data_type="email"),
        "Phone": FieldMeta(api_name="Phone", data_type="phone"),
    }


def _columns() -> list[ColumnSamples]:
    return [
        ColumnSamples(name="FirstName", samples=("Arjun", "Rani", "Kabir", "Meera", "Dev")),
        ColumnSamples(
            name="Email",
            samples=(
                "a@example.invalid",
                "b@example.invalid",
                "c@example.invalid",
                "d@example.invalid",
                "e@example.invalid",
            ),
        ),
        ColumnSamples(name="Pet", samples=("blue", "N/A", "x", "pending", "??")),
    ]


def test_read_column_samples_caps_at_five(tmp_path: Path) -> None:
    path = tmp_path / "in.csv"
    path.write_text(
        "Name,Email\n" + "".join(f"n{i},u{i}@example.invalid\n" for i in range(9)),
        encoding="utf-8",
    )
    columns = read_column_samples(str(path))
    assert [column.name for column in columns] == ["Name", "Email"]
    assert len(columns[0].samples) == 5
    assert columns[0].samples[0] == "n0"


def test_read_column_samples_rejects_missing(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(ValueError):
        read_column_samples(str(tmp_path / "nope.csv"))


def test_heuristic_mapping_is_structurally_valid() -> None:
    draft = heuristic_mapping(_columns(), _fields())
    kept, dropped = validate_mapping(_columns(), _fields(), draft)
    assert dropped == []
    assert len(kept.suggestions) == 3
    by_name = {item.source_column: item for item in kept.suggestions}
    assert by_name["FirstName"].target_api_name == "First_Name"
    assert by_name["Email"].target_api_name == "Email"
    assert by_name["Pet"].target_api_name is None


def test_validate_mapping_drops_every_bad_shape() -> None:
    from zohokit.ai.schemas import MappingDraft, MappingSuggestion

    def _sug(name: str, target: str | None, conf: float = 0.9) -> MappingSuggestion:
        return MappingSuggestion(
            source_column=name,
            target_api_name=target,
            transform=["trim"],
            confidence=conf,
            rationale="r",
            evidence_samples_idx=[0],
        )

    columns, fields = _columns(), _fields()
    draft = MappingDraft(
        suggestions=[
            _sug("FirstName", "Nope"),
            _sug("Email", "Email"),
            _sug("Email", "Phone"),
            _sug("Ghost", "Email"),
            MappingSuggestion(
                source_column="Pet",
                target_api_name=None,
                transform=[],
                confidence=0.1,
                rationale="r",
                evidence_samples_idx=[0],
            ),
        ]
    )
    kept, dropped = validate_mapping(columns, fields, draft)
    reasons = sorted(item.reason for item in dropped)
    assert reasons == [
        "duplicate suggestion",
        "no suggestion proposed; abstained",
        "unknown source column",
        "unknown target field",
    ]
    assert [item.source_column for item in kept.suggestions] == ["FirstName", "Email", "Pet"]
    assert kept.suggestions[0].target_api_name is None
    assert kept.suggestions[1].target_api_name == "Email"


def test_validate_mapping_abstention_rules() -> None:
    from zohokit.ai.schemas import MappingDraft, MappingSuggestion

    columns, fields = _columns(), _fields()
    low = MappingDraft(
        suggestions=[
            MappingSuggestion(
                source_column="Email",
                target_api_name="Email",
                transform=["trim"],
                confidence=0.3,
                rationale="r",
                evidence_samples_idx=[0],
            ),
            MappingSuggestion(
                source_column="FirstName",
                target_api_name="First_Name",
                transform=["trim"],
                confidence=0.9,
                rationale="r",
                evidence_samples_idx=[9],
            ),
            MappingSuggestion(
                source_column="Pet",
                target_api_name=None,
                transform=["trim"],
                confidence=0.1,
                rationale="r",
                evidence_samples_idx=[0],
            ),
        ]
    )
    kept, dropped = validate_mapping(columns, fields, low)
    assert sorted(item.reason for item in dropped) == [
        "abstained entry proposes transforms",
        "mapped below the confidence floor",
        "no suggestion proposed; abstained",
        "no suggestion proposed; abstained",
        "no suggestion proposed; abstained",
        "sample index out of range",
    ]
    assert all(item.target_api_name is None for item in kept.suggestions)


def _mapping_provider(columns: list[ColumnSamples], raw: str) -> FakeProvider:
    from zohokit.ai.prompts import load_template
    from zohokit.ai.redaction import build_prompt
    from zohokit.core.redact import Redactor
    from zohokit.modules.migration.suggest import mapping_variables

    variables = mapping_variables(columns, _fields())
    prompt = build_prompt(load_template("mapping"), variables, redactor=Redactor())
    return FakeProvider({prompt.prompt_hash: raw}, model="test-fake")


def test_suggest_mapping_disabled_runs_heuristic() -> None:
    result = suggest_mapping(_columns(), _fields(), "Contacts", provider=None)
    assert result.ai_status == "disabled"
    assert len(result.suggestions) == 3
    assert result.usage.status == "disabled"


def test_suggest_mapping_ai_path_keeps_valid() -> None:
    columns = _columns()
    raw = json.dumps(
        {
            "suggestions": [
                {
                    "source_column": "FirstName",
                    "target_api_name": "First_Name",
                    "transform": ["trim"],
                    "confidence": 0.95,
                    "rationale": "header match",
                    "evidence_samples_idx": [0, 1],
                },
                {
                    "source_column": "Email",
                    "target_api_name": "Email",
                    "transform": ["trim", "casefold"],
                    "confidence": 0.97,
                    "rationale": "shape match",
                    "evidence_samples_idx": [0, 1],
                },
                {
                    "source_column": "Pet",
                    "target_api_name": None,
                    "transform": [],
                    "confidence": 0.2,
                    "rationale": "no fit",
                    "evidence_samples_idx": [0],
                },
            ]
        }
    )
    result = suggest_mapping(
        columns, _fields(), "Contacts", provider=_mapping_provider(columns, raw)
    )
    assert result.ai_status == "ok"
    assert result.model == "test-fake"
    assert result.prompt_version == "v1"
    assert result.dropped == []
    assert "First_Name" in render_mapping_table(result)
    assert "AI suggestion" in render_mapping_html(result)


def test_suggest_mapping_ai_bad_entries_dropped_and_reported() -> None:
    columns = _columns()
    raw = json.dumps(
        {
            "suggestions": [
                {
                    "source_column": "FirstName",
                    "target_api_name": "Nope",
                    "transform": ["trim"],
                    "confidence": 0.9,
                    "rationale": "wrong",
                    "evidence_samples_idx": [0],
                },
                {
                    "source_column": "Email",
                    "target_api_name": "Email",
                    "transform": ["trim"],
                    "confidence": 0.9,
                    "rationale": "right",
                    "evidence_samples_idx": [0],
                },
                {
                    "source_column": "Pet",
                    "target_api_name": None,
                    "transform": [],
                    "confidence": 0.1,
                    "rationale": "abstain",
                    "evidence_samples_idx": [],
                },
            ]
        }
    )
    result = suggest_mapping(
        columns, _fields(), "Contacts", provider=_mapping_provider(columns, raw)
    )
    assert result.ai_status == "ok"
    assert [item.source_column for item in result.suggestions] == ["FirstName", "Email", "Pet"]
    assert result.suggestions[0].target_api_name is None
    assert [(item.source_column, item.reason) for item in result.dropped] == [
        ("FirstName", "unknown target field"),
        ("FirstName", "no suggestion proposed; abstained"),
    ]
    assert "dropped FirstName" in render_mapping_table(result)


def test_suggest_mapping_ai_malformed_falls_back() -> None:
    columns = _columns()
    from zohokit.ai.prompts import load_template
    from zohokit.ai.redaction import build_prompt
    from zohokit.core.redact import Redactor
    from zohokit.modules.migration.suggest import mapping_variables

    variables = mapping_variables(columns, _fields())
    prompt = build_prompt(load_template("mapping"), variables, redactor=Redactor())
    provider = FakeProvider({prompt.prompt_hash: "not json {{{"}, model="test-fake")
    result = suggest_mapping(columns, _fields(), "Contacts", provider=provider)
    assert result.ai_status == "fallback"
    assert len(result.suggestions) == 3


def test_draft_yaml_is_a_reviewable_list() -> None:
    import yaml

    result = suggest_mapping(_columns(), _fields(), "Contacts", provider=None)
    text = draft_yaml(result)
    assert text.startswith("# Mapping draft")
    assert "status: disabled" in text
    parsed = yaml.safe_load(text)
    assert isinstance(parsed, list) and len(parsed) == 3
    assert parsed[0]["source_column"] == "FirstName"


def test_guess_transform_dates_and_abstention() -> None:
    good = guess_transform(
        ["31/12/2026", "15/01/2027", "28/02/2027", "30/06/2027", "01/04/2027"], "date"
    )
    assert good.transform == "date(format=%d/%m/%Y)"
    assert good.evidence_samples_idx == [0, 1, 2, 3, 4]
    junk = guess_transform(["blue", "N/A", "??", "", " - "], "date")
    assert junk.transform is None
    assert junk.confidence < 0.6


def test_guess_transform_money_needs_currency() -> None:
    amounts = ["45000.00", "120000.50", "78000.00", "250000.00", "9500.75"]
    rows = [{"Currency": "INR"} for _ in amounts]
    assert (
        guess_transform(amounts, "currency", rows=rows, currency_col="Currency").transform
        == "money(currency_col=Currency)"
    )


def test_validate_transform_partial_failure() -> None:
    assert validate_transform(
        ["31/12/2026", "not a date"],
        [{}, {}],
        __import__("zohokit.ai.schemas", fromlist=["TransformDraft"]).TransformDraft(
            transform="date(format=%d/%m/%Y)",
            confidence=0.9,
            rationale="r",
            evidence_samples_idx=[0, 1],
        ),
    ) == ["parse: sample #1 fails the proposed transform"]


def _transform_provider(column: str, samples: list[str], raw: str) -> FakeProvider:
    from zohokit.ai.prompts import load_template
    from zohokit.ai.redaction import build_prompt
    from zohokit.core.redact import Redactor
    from zohokit.modules.migration.suggest import transform_variables

    variables = transform_variables(column, samples, "date")
    prompt = build_prompt(load_template("transform"), variables, redactor=Redactor())
    return FakeProvider({prompt.prompt_hash: raw}, model="test-fake")


def test_suggest_transform_disabled_and_ai_paths() -> None:
    samples = ["31/12/2026", "15/01/2027", "28/02/2027", "30/06/2027", "01/04/2027"]
    disabled = suggest_transform("Close_Date", samples, "date", provider=None)
    assert disabled.ai_status == "disabled"
    assert disabled.suggestion.transform == "date(format=%d/%m/%Y)"
    assert "date(format=%d/%m/%Y)" in render_transform_table(disabled)

    raw = json.dumps(
        {
            "transform": "date(format=%d/%m/%Y)",
            "confidence": 0.9,
            "rationale": "day-first",
            "evidence_samples_idx": [0, 1, 2, 3, 4],
        }
    )
    result = suggest_transform(
        "Close_Date",
        samples,
        "date",
        provider=_transform_provider("Close_Date", samples, raw),
    )
    assert result.ai_status == "ok"
    assert result.suggestion.transform == "date(format=%d/%m/%Y)"
    assert "AI suggestion" in render_transform_html(result)


def test_suggest_transform_ai_failure_dropped_and_reported() -> None:
    samples = ["31/12/2026", "15/01/2027", "28/02/2027", "30/06/2027", "01/04/2027"]
    raw = json.dumps(
        {
            "transform": "teleport",
            "confidence": 0.9,
            "rationale": "wrong",
            "evidence_samples_idx": [0, 1, 2, 3, 4],
        }
    )
    result = suggest_transform(
        "Close_Date",
        samples,
        "date",
        provider=_transform_provider("Close_Date", samples, raw),
    )
    assert result.ai_status == "fallback"
    assert result.suggestion.transform == "date(format=%d/%m/%Y)"
    assert result.dropped[0].reason == "reference: transform does not parse"
    assert "dropped Close_Date" in render_transform_table(result)


class _CapturingProvider(FakeProvider):
    """FakeProvider that records every prompt it receives (STD-AI8 tests)."""

    def __init__(self, recordings: dict[str, str]) -> None:
        super().__init__(recordings, model="test-fake")
        self.prompts: list[object] = []

    def complete_structured(  # type: ignore[override]
        self, prompt: object, schema: object, *, max_tokens: int, temperature: float = 0.0
    ) -> object:
        self.prompts.append(prompt)
        return super().complete_structured(
            prompt,  # type: ignore[arg-type]
            schema,  # type: ignore[arg-type]
            max_tokens=max_tokens,
            temperature=temperature,
        )


def _prompt_text(provider: _CapturingProvider) -> str:
    assert len(provider.prompts) == 1
    prompt = provider.prompts[0]
    assert hasattr(prompt, "text")
    text = prompt.text  # type: ignore[attr-defined]
    assert isinstance(text, str)
    return text


def test_mapping_prompt_carries_no_person_names() -> None:
    """STD-AI8: a planted name from a name-like column never reaches the model."""
    from zohokit.ai.prompts import load_template
    from zohokit.ai.redaction import build_prompt
    from zohokit.core.redact import Redactor
    from zohokit.modules.migration.suggest import mapping_variables

    names = ("Asha Rao", "Dev Patel", "Rani Iyer", "Kabir Shah", "Meera Nair")
    columns = [
        ColumnSamples(name="Contact Person", samples=names),
        ColumnSamples(
            name="Email",
            samples=(
                "a@example.invalid",
                "b@example.invalid",
                "c@example.invalid",
                "d@example.invalid",
                "e@example.invalid",
            ),
        ),
    ]
    fields = {
        "Last_Name": FieldMeta(api_name="Last_Name", data_type="string"),
        "Email": FieldMeta(api_name="Email", data_type="email"),
    }
    raw = json.dumps(
        {
            "suggestions": [
                {
                    "source_column": "Contact Person",
                    "target_api_name": "Last_Name",
                    "transform": ["trim"],
                    "confidence": 0.65,
                    "rationale": "header match",
                    "evidence_samples_idx": [0, 1],
                },
                {
                    "source_column": "Email",
                    "target_api_name": "Email",
                    "transform": ["trim", "casefold"],
                    "confidence": 0.97,
                    "rationale": "shape match",
                    "evidence_samples_idx": [0, 1],
                },
            ]
        }
    )
    variables = mapping_variables(columns, fields)
    prompt = build_prompt(load_template("mapping"), variables, redactor=Redactor())
    provider = _CapturingProvider({prompt.prompt_hash: raw})
    result = suggest_mapping(columns, fields, "Contacts", provider=provider)
    assert result.ai_status == "ok"
    text = _prompt_text(provider)
    for name in names:
        assert name not in text
    assert "<name: 2 words>" in text
    assert "Contact Person:" in text


def test_mapping_prompt_masks_pii_flagged_columns() -> None:
    """STD-AI8: columns the mapping marks pii:true mask like name columns."""
    from zohokit.ai.prompts import load_template
    from zohokit.ai.redaction import build_prompt
    from zohokit.core.redact import Redactor
    from zohokit.modules.migration.suggest import mapping_variables

    columns = [
        ColumnSamples(name="Notes", samples=("Asha Rao", "tall", "short", "none", "later")),
        ColumnSamples(
            name="Email",
            samples=(
                "a@example.invalid",
                "b@example.invalid",
                "c@example.invalid",
                "d@example.invalid",
                "e@example.invalid",
            ),
        ),
    ]
    fields = {
        "Description": FieldMeta(api_name="Description", data_type="string"),
        "Email": FieldMeta(api_name="Email", data_type="email"),
    }
    raw = json.dumps(
        {
            "suggestions": [
                {
                    "source_column": "Notes",
                    "target_api_name": "Description",
                    "transform": ["trim"],
                    "confidence": 0.7,
                    "rationale": "header match",
                    "evidence_samples_idx": [0, 1],
                },
                {
                    "source_column": "Email",
                    "target_api_name": "Email",
                    "transform": ["trim", "casefold"],
                    "confidence": 0.97,
                    "rationale": "shape match",
                    "evidence_samples_idx": [0, 1],
                },
            ]
        }
    )
    variables = mapping_variables(columns, fields, pii_columns={"Notes"})
    prompt = build_prompt(load_template("mapping"), variables, redactor=Redactor())
    provider = _CapturingProvider({prompt.prompt_hash: raw})
    result = suggest_mapping(columns, fields, "Leads", provider=provider, pii_columns={"Notes"})
    assert result.ai_status == "ok"
    text = _prompt_text(provider)
    assert "Asha Rao" not in text
    assert "Notes: <name: 2 words>" in text


def test_pii_source_columns_reads_mapping_flags() -> None:
    from zohokit.modules.migration.mapping import FieldMapping
    from zohokit.modules.migration.suggest import pii_source_columns

    fields = {
        "Email": FieldMapping(**{"from": "Email", "pii": True}),
        "Phone": FieldMapping(**{"from": "Phone"}),
        "Notes": FieldMapping(**{"from": None, "pii": True}),
    }
    assert pii_source_columns(fields) == frozenset({"Email"})


def test_transform_prompt_carries_no_person_names() -> None:
    """STD-AI8: a planted name from a name-like column never reaches the model."""
    from zohokit.ai.prompts import load_template
    from zohokit.ai.redaction import build_prompt
    from zohokit.core.redact import Redactor
    from zohokit.modules.migration.suggest import transform_variables

    samples = ["  Asha Rao ", "Rani Iyer  ", "  Kabir Shah", "Meera Nair ", " Dev Patel  "]
    raw = json.dumps(
        {
            "transform": "trim",
            "confidence": 0.95,
            "rationale": "trims every sample",
            "evidence_samples_idx": [0, 1, 2, 3, 4],
        }
    )
    variables = transform_variables("Full Name", samples, "text")
    prompt = build_prompt(load_template("transform"), variables, redactor=Redactor())
    provider = _CapturingProvider({prompt.prompt_hash: raw})
    result = suggest_transform("Full Name", samples, "text", provider=provider)
    assert result.ai_status == "ok"
    text = _prompt_text(provider)
    for name in ("Asha Rao", "Rani Iyer", "Kabir Shah", "Meera Nair", "Dev Patel"):
        assert name not in text
    assert "<name: 2 words>" in text

    flagged = transform_variables("Nickname", ["Asha Rao"], "text", pii_columns={"Nickname"})
    assert flagged["samples"] == "<name: 2 words>"
