"""Mapping and transform suggesters (AI-MIG-1, AI-MIG-2).

From CSV headers plus 5 sample values per column and target field
metadata, these helpers propose mapping entries (or single value
transforms) as *suggestions* for human review — nothing is applied.
Every prompt passes the redactor first; with no provider the
deterministic heuristic runs instead. Proposed transforms are applied
to the samples before they are shown: anything below 100% parse
success is dropped and reported.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import yaml
from jinja2 import Environment
from pydantic import BaseModel, ConfigDict, Field

from zohokit.ai.badge import AI_BADGE_CSS, ai_badge_html
from zohokit.ai.models import AiUsage
from zohokit.ai.pipeline import AiRequest, run_ai
from zohokit.ai.prompts import load_template
from zohokit.ai.providers import LLMProvider
from zohokit.ai.schemas import MappingDraft, MappingSuggestion, TransformDraft
from zohokit.connectors.sources import csv_reader
from zohokit.core.redact import Redactor
from zohokit.modules.migration.mapping import TransformError, apply_transforms, coerce_transform
from zohokit.modules.migration.metadata import FieldMeta

#: Samples shown per column (prompt input and validation set alike).
SAMPLE_LIMIT = 5


@dataclass(frozen=True)
class ColumnSamples:
    """One source column plus its sample values."""

    name: str
    samples: tuple[str, ...]


class DroppedSuggestion(BaseModel):
    """A proposal removed before display, with a value-free reason."""

    model_config = ConfigDict(frozen=True)

    source_column: str = ""
    reason: str = ""


class SuggestMappingResult(BaseModel):
    """One mapping-suggestion run: draft entries plus traceability."""

    model_config = ConfigDict(frozen=True)

    source: str = "ai"
    model: str = ""
    prompt_version: str = "template"
    prompt_hash: str = ""
    ai_status: str = "template"
    target_module: str = ""
    suggestions: list[MappingSuggestion] = Field(default_factory=list)
    dropped: list[DroppedSuggestion] = Field(default_factory=list)
    usage: AiUsage = Field(default_factory=AiUsage)


class SuggestTransformResult(BaseModel):
    """One transform-suggestion run: the proposal plus traceability."""

    model_config = ConfigDict(frozen=True)

    source: str = "ai"
    model: str = ""
    prompt_version: str = "template"
    prompt_hash: str = ""
    ai_status: str = "template"
    column: str = ""
    target_type: str = ""
    suggestion: TransformDraft = Field(default_factory=TransformDraft)
    dropped: list[DroppedSuggestion] = Field(default_factory=list)
    usage: AiUsage = Field(default_factory=AiUsage)


def read_column_samples(path: str, *, limit: int = SAMPLE_LIMIT) -> list[ColumnSamples]:
    """Read a CSV header plus the first *limit* values per column."""
    try:
        stream = csv_reader.open_csv(path)
    except (csv_reader.CsvReadError, OSError) as exc:
        raise ValueError(str(exc)) from exc
    columns: dict[str, list[str]] = {name: [] for name in stream.dialect.header}
    try:
        for _, row, issue in stream.rows():
            if issue is not None or row is None:
                continue
            done = True
            for name in columns:
                if len(columns[name]) < limit:
                    columns[name].append(row.get(name, ""))
                    done = False
            if done:
                break
    finally:
        stream.close()
    return [ColumnSamples(name=name, samples=tuple(values)) for name, values in columns.items()]


def target_field_lines(fields: dict[str, FieldMeta]) -> tuple[str, set[str]]:
    """Render target metadata for the prompt; return lines + known names."""
    lines = []
    for name in sorted(fields):
        meta = fields[name]
        line = f"{meta.api_name} ({meta.data_type or 'string'}, required={meta.system_mandatory})"
        if meta.pick_list_values:
            line += f", values=[{'|'.join(meta.pick_list_values)}]"
        lines.append(line)
    return "\n".join(lines), set(fields)


def mapping_variables(columns: list[ColumnSamples], fields: dict[str, FieldMeta]) -> dict[str, str]:
    """Render deterministic mapping prompt variables."""
    column_lines = [f"{column.name}: {' | '.join(column.samples)}" for column in columns]
    target_lines, _ = target_field_lines(fields)
    return {"source_columns": "\n".join(column_lines), "target_fields": target_lines}


def _normalize_header(name: str) -> str:
    return "".join(char for char in name.casefold() if char.isalnum())


def heuristic_mapping(
    columns: list[ColumnSamples], fields: dict[str, FieldMeta], *, default_region: str | None = None
) -> MappingDraft:
    """Deterministic name/shape matcher; also the AI fallback (AI-MIG-1)."""
    by_normalized = {_normalize_header(name): name for name in fields}
    suggestions = []
    for column in columns:
        key = _normalize_header(column.name)
        target: str | None = None
        confidence = 0.0
        if key in by_normalized and key:
            target = by_normalized[key]
            confidence = 0.9
        else:
            lowered = column.name.casefold()
            for api_name in sorted(fields):
                normalized = _normalize_header(api_name)
                if key and (normalized in key or key in normalized):
                    target = api_name
                    confidence = 0.75
                    break
            if target is None:
                if "mail" in lowered:
                    target, confidence = "Email", 0.7
                elif "mobile" in lowered or "phone" in lowered or lowered == "tel":
                    target, confidence = "Phone", 0.7
        transforms: list[Any] = []
        if target is not None:
            dtype = fields[target].data_type.casefold()
            if dtype == "email":
                transforms = ["trim", "casefold"]
            elif dtype == "phone":
                if default_region:
                    transforms = ["trim", f"e164(region={default_region})"]
                else:
                    transforms = ["trim"]
            else:
                transforms = ["trim"]
        suggestions.append(
            MappingSuggestion(
                source_column=column.name,
                target_api_name=target if confidence >= 0.6 else None,
                transform=transforms if confidence >= 0.6 else [],
                confidence=confidence if target is not None else 0.0,
                rationale="heuristic header match" if target else "no target fits; abstained",
                evidence_samples_idx=[0] if column.samples else [],
            )
        )
    return MappingDraft(suggestions=suggestions)


def validate_mapping(
    columns: list[ColumnSamples], fields: dict[str, FieldMeta], draft: MappingDraft
) -> tuple[MappingDraft, list[DroppedSuggestion]]:
    """Keep structurally valid proposals; drop and report the rest.

    Drops unknown columns, duplicate columns, out-of-range evidence,
    unknown targets, unknown transforms, transforms on abstentions, and
    mappings below the 0.6 confidence floor. Missing columns are filled
    with heuristic abstentions and reported.
    """
    names = [column.name for column in columns]
    samples_by_name = {column.name: column.samples for column in columns}
    kept: list[MappingSuggestion] = []
    dropped: list[DroppedSuggestion] = []
    seen: set[str] = set()
    for suggestion in draft.suggestions:
        name = suggestion.source_column
        if name not in names:
            dropped.append(DroppedSuggestion(source_column=name, reason="unknown source column"))
            continue
        if name in seen:
            dropped.append(DroppedSuggestion(source_column=name, reason="duplicate suggestion"))
            continue
        samples = samples_by_name[name]
        if any(
            not isinstance(i, int) or i < 0 or i >= len(samples)
            for i in suggestion.evidence_samples_idx
        ):
            dropped.append(
                DroppedSuggestion(source_column=name, reason="sample index out of range")
            )
            continue
        if suggestion.target_api_name is not None and suggestion.target_api_name not in fields:
            dropped.append(DroppedSuggestion(source_column=name, reason="unknown target field"))
            continue
        try:
            for entry in suggestion.transform:
                coerce_transform(entry)
        except TransformError:
            dropped.append(DroppedSuggestion(source_column=name, reason="unknown transform"))
            continue
        if suggestion.confidence < 0.6 and suggestion.target_api_name is not None:
            dropped.append(
                DroppedSuggestion(source_column=name, reason="mapped below the confidence floor")
            )
            continue
        if suggestion.transform and suggestion.target_api_name is None:
            dropped.append(
                DroppedSuggestion(source_column=name, reason="abstained entry proposes transforms")
            )
            continue
        seen.add(name)
        kept.append(suggestion)
    for name in names:
        if name not in seen:
            kept.append(
                MappingSuggestion(
                    source_column=name,
                    target_api_name=None,
                    transform=[],
                    confidence=0.0,
                    rationale="no suggestion proposed; abstained",
                    evidence_samples_idx=[],
                )
            )
            dropped.append(
                DroppedSuggestion(source_column=name, reason="no suggestion proposed; abstained")
            )
    order = {name: index for index, name in enumerate(names)}
    kept.sort(key=lambda item: order.get(item.source_column, len(order)))
    return MappingDraft(suggestions=kept), dropped


def suggest_mapping(
    columns: list[ColumnSamples],
    fields: dict[str, FieldMeta],
    target_module: str,
    *,
    provider: LLMProvider | None,
    allow_pii: bool = False,
    budget_tokens: int | None = None,
    default_region: str | None = None,
    redactor: Redactor | None = None,
) -> SuggestMappingResult:
    """Propose mapping entries; invalid ones are dropped and reported."""
    variables = mapping_variables(columns, fields)
    if provider is None:
        draft = heuristic_mapping(columns, fields, default_region=default_region)
        return SuggestMappingResult(
            model="",
            prompt_version="template",
            prompt_hash="",
            ai_status="disabled",
            target_module=target_module,
            suggestions=draft.suggestions,
            dropped=[],
            usage=AiUsage(status="disabled"),
        )
    template = load_template("mapping")
    outcome = run_ai(
        provider,
        AiRequest(
            template=template,
            variables=variables,
            allow_pii=allow_pii,
            budget_tokens=budget_tokens,
            temperature=0.0,
        ),
        MappingDraft,
        fallback=lambda: heuristic_mapping(columns, fields, default_region=default_region),
        redactor=redactor,
    )
    if outcome.ai_status == "fallback":
        return SuggestMappingResult(
            model=outcome.model,
            prompt_version=outcome.prompt_version,
            prompt_hash=outcome.prompt_hash,
            ai_status="fallback",
            target_module=target_module,
            suggestions=list(outcome.data.suggestions),
            dropped=[],
            usage=outcome.usage,
        )
    kept, dropped = validate_mapping(columns, fields, outcome.data)
    if not kept.suggestions or all(item.target_api_name is None for item in kept.suggestions):
        heuristic = heuristic_mapping(columns, fields, default_region=default_region)
        return SuggestMappingResult(
            model=outcome.model,
            prompt_version=outcome.prompt_version,
            prompt_hash=outcome.prompt_hash,
            ai_status="fallback",
            target_module=target_module,
            suggestions=heuristic.suggestions,
            dropped=dropped,
            usage=outcome.usage.model_copy(update={"status": "fallback"}),
        )
    return SuggestMappingResult(
        model=outcome.model,
        prompt_version=outcome.prompt_version,
        prompt_hash=outcome.prompt_hash,
        ai_status=outcome.ai_status,
        target_module=target_module,
        suggestions=kept.suggestions,
        dropped=dropped,
        usage=outcome.usage,
    )


#: Candidate transforms tried by the deterministic guesser per target type.
_GUESS_CANDIDATES: dict[str, list[str]] = {
    "text": ["trim", "casefold"],
    "email": ["trim", "casefold"],
    "phone": ["trim"],
    "date": ["date(format=%d/%m/%Y)", "date(format=%Y-%m-%d)", "date"],
    "currency": ["trim"],
}


def guess_transform(
    samples: list[str],
    target_type: str,
    *,
    rows: list[dict[str, str]] | None = None,
    default_region: str | None = None,
    currency_col: str | None = None,
) -> TransformDraft:
    """Deterministic proposer; also the AI fallback (AI-MIG-2).

    Tries semantic candidates first and returns the first with 100%
    parse success over the samples, else abstains (null).
    """
    if not samples:
        return TransformDraft(
            transform=None,
            confidence=0.0,
            rationale="no samples; abstained",
            evidence_samples_idx=[],
        )
    candidates = list(_GUESS_CANDIDATES.get(target_type, ["trim"]))
    if target_type == "phone" and default_region:
        candidates = [f"e164(region={default_region})", "e164", "trim"]
    elif target_type == "phone":
        candidates = ["e164", "trim"]
    if target_type == "currency" and currency_col:
        candidates = [f"money(currency_col={currency_col})", "trim"]
    check_rows = rows if rows is not None else [{} for _ in samples]
    for candidate in candidates:
        try:
            spec = coerce_transform(candidate)
        except TransformError:
            continue
        ok = True
        for sample, row in zip(samples, check_rows, strict=True):
            try:
                apply_transforms(sample, row, [spec])
            except TransformError:
                ok = False
                break
        if ok:
            return TransformDraft(
                transform=candidate,
                confidence=0.7,
                rationale=f"{candidate} parses every sample",
                evidence_samples_idx=list(range(len(samples))),
            )
    return TransformDraft(
        transform=None,
        confidence=0.2,
        rationale="no candidate parses every sample; abstained",
        evidence_samples_idx=[],
    )


def validate_transform(
    samples: list[str], rows: list[dict[str, str]], draft: TransformDraft
) -> list[str]:
    """Apply the proposal to every sample; value-free violation strings."""
    violations: list[str] = []
    if draft.transform is None:
        if draft.confidence >= 0.6:
            violations.append("abstention: null proposal needs low confidence")
        return violations
    if draft.confidence < 0.6:
        violations.append("abstention: proposed transform needs high confidence")
    try:
        spec = coerce_transform(draft.transform)
    except TransformError:
        violations.append("reference: transform does not parse")
        return violations
    for index, (sample, row) in enumerate(zip(samples, rows, strict=True)):
        try:
            apply_transforms(sample, row, [spec])
        except TransformError:
            violations.append(f"parse: sample #{index} fails the proposed transform")
            break
    if set(draft.evidence_samples_idx) != set(range(len(samples))):
        violations.append("evidence: must list every checked sample index")
    return violations


TransformTarget = Literal["text", "email", "phone", "date", "currency"]


def suggest_transform(
    column: str,
    samples: list[str],
    target_type: str,
    *,
    rows: list[dict[str, str]] | None = None,
    provider: LLMProvider | None,
    allow_pii: bool = False,
    budget_tokens: int | None = None,
    default_region: str | None = None,
    currency_col: str | None = None,
    redactor: Redactor | None = None,
) -> SuggestTransformResult:
    """Propose one transform; failures are dropped and reported (AI-MIG-2)."""
    check_rows = rows if rows is not None else [{} for _ in samples]
    variables = {
        "column": column,
        "samples": "\n".join(samples),
        "target_type": target_type,
    }
    if provider is None:
        draft = guess_transform(
            samples,
            target_type,
            rows=check_rows,
            default_region=default_region,
            currency_col=currency_col,
        )
        return SuggestTransformResult(
            model="",
            prompt_version="template",
            prompt_hash="",
            ai_status="disabled",
            column=column,
            target_type=target_type,
            suggestion=draft,
            dropped=[],
            usage=AiUsage(status="disabled"),
        )
    template = load_template("transform")
    outcome = run_ai(
        provider,
        AiRequest(
            template=template,
            variables=variables,
            allow_pii=allow_pii,
            budget_tokens=budget_tokens,
            temperature=0.0,
        ),
        TransformDraft,
        fallback=lambda: guess_transform(
            samples,
            target_type,
            rows=check_rows,
            default_region=default_region,
            currency_col=currency_col,
        ),
        redactor=redactor,
    )
    if outcome.ai_status == "fallback":
        return SuggestTransformResult(
            model=outcome.model,
            prompt_version=outcome.prompt_version,
            prompt_hash=outcome.prompt_hash,
            ai_status="fallback",
            column=column,
            target_type=target_type,
            suggestion=outcome.data,
            dropped=[],
            usage=outcome.usage,
        )
    violations = validate_transform(samples, check_rows, outcome.data)
    if violations:
        heuristic = guess_transform(
            samples,
            target_type,
            rows=check_rows,
            default_region=default_region,
            currency_col=currency_col,
        )
        return SuggestTransformResult(
            model=outcome.model,
            prompt_version=outcome.prompt_version,
            prompt_hash=outcome.prompt_hash,
            ai_status="fallback",
            column=column,
            target_type=target_type,
            suggestion=heuristic,
            dropped=[DroppedSuggestion(source_column=column, reason=violations[0])],
            usage=outcome.usage.model_copy(update={"status": "fallback"}),
        )
    return SuggestTransformResult(
        model=outcome.model,
        prompt_version=outcome.prompt_version,
        prompt_hash=outcome.prompt_hash,
        ai_status=outcome.ai_status,
        column=column,
        target_type=target_type,
        suggestion=outcome.data,
        dropped=[],
        usage=outcome.usage,
    )


def render_mapping_table(result: SuggestMappingResult) -> str:
    """Human-readable draft summary with drop notes."""
    lines = [
        f"target: {result.target_module} (source: {result.source}, status: {result.ai_status})"
    ]
    for item in result.suggestions:
        target = item.target_api_name or "—"
        lines.append(f"- {item.source_column} -> {target} [{item.confidence:.2f}]")
    for dropped in result.dropped:
        lines.append(f"! dropped {dropped.source_column}: {dropped.reason}")
    return "\n".join(lines) + "\n"


_MAPPING_HTML = """\
<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Mapping draft ({{ target_module }})</title>
<style>{{ badge_css }}body{font-family:sans-serif;max-width:60em;margin:2em auto;}
table{border-collapse:collapse;}td,th{border:1px solid #ccc;padding:0.3em 0.6em;}</style>
</head><body>
<h1>Mapping draft ({{ target_module }})</h1>
<p>source: {{ source }} · status: {{ ai_status }}</p>
<p>model: {{ model }} · prompt: {{ prompt_version }}</p>
<table><tr><th>source column</th><th>target</th><th>confidence</th><th></th></tr>
{% for item in suggestions %}
<tr><td>{{ item.source_column }}</td><td>{{ item.target }}</td>
<td>{{ item.confidence }}</td><td>{{ badge(item.confidence, item.ai) }}</td></tr>
{% endfor %}
</table>
{% if dropped %}
<h2>Dropped proposals</h2>
<ul>{% for item in dropped %}<li>{{ item.source_column }}: {{ item.reason }}</li>{% endfor %}</ul>
{% endif %}
</body></html>
"""


def render_mapping_html(result: SuggestMappingResult) -> str:
    """HTML draft; AI items carry the suggestion badge + confidence."""
    template = Environment(autoescape=True).from_string(_MAPPING_HTML)
    show_badge = result.ai_status not in ("disabled", "template", "fallback")
    return template.render(
        target_module=result.target_module,
        source=result.source,
        ai_status=result.ai_status,
        model=result.model,
        prompt_version=result.prompt_version,
        suggestions=[
            {
                "source_column": item.source_column,
                "target": item.target_api_name or "—",
                "confidence": f"{item.confidence:.2f}",
                "ai": show_badge,
            }
            for item in result.suggestions
        ],
        dropped=[
            {"source_column": item.source_column, "reason": item.reason} for item in result.dropped
        ],
        badge=(lambda confidence, ai: ai_badge_html(float(confidence)) if ai else ""),
        badge_css=AI_BADGE_CSS,
    )


def render_transform_table(result: SuggestTransformResult) -> str:
    """Human-readable single proposal with drop notes."""
    lines = [
        f"column: {result.column} (source: {result.source}, status: {result.ai_status})",
        f"proposed: {result.suggestion.transform} [{result.suggestion.confidence:.2f}]",
    ]
    for dropped in result.dropped:
        lines.append(f"! dropped {dropped.source_column}: {dropped.reason}")
    return "\n".join(lines) + "\n"


_TRANSFORM_HTML = """\
<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Transform draft ({{ column }})</title>
<style>{{ badge_css }}body{font-family:sans-serif;max-width:60em;margin:2em auto;}</style>
</head><body>
<h1>Transform draft ({{ column }} → {{ target_type }})</h1>
<p>source: {{ source }} · status: {{ ai_status }}</p>
<p>model: {{ model }} · prompt: {{ prompt_version }}</p>
<p>proposed: <code>{{ transform }}</code> (confidence {{ confidence }}) {{ badge }}</p>
{% if dropped %}
<h2>Dropped proposals</h2>
<ul>{% for item in dropped %}<li>{{ item.source_column }}: {{ item.reason }}</li>{% endfor %}</ul>
{% endif %}
</body></html>
"""


def render_transform_html(result: SuggestTransformResult) -> str:
    """HTML proposal; the AI item carries the suggestion badge + confidence."""
    template = Environment(autoescape=True).from_string(_TRANSFORM_HTML)
    show_badge = result.ai_status not in ("disabled", "template", "fallback")
    badge = ai_badge_html(result.suggestion.confidence) if show_badge else ""
    return template.render(
        column=result.column,
        target_type=result.target_type,
        source=result.source,
        ai_status=result.ai_status,
        model=result.model,
        prompt_version=result.prompt_version,
        transform=result.suggestion.transform or "—",
        confidence=f"{result.suggestion.confidence:.2f}",
        badge=badge,
        dropped=[
            {"source_column": item.source_column, "reason": item.reason} for item in result.dropped
        ],
        badge_css=AI_BADGE_CSS,
    )


def draft_yaml(result: SuggestMappingResult) -> str:
    """Render the draft file: traceability header plus suggestion entries."""
    header = [
        "# Mapping draft proposed by zohokit (review before use).",
        f"# source: {result.source}",
        f"# model: {result.model or 'deterministic heuristic'}",
        f"# prompt: {result.prompt_version} {result.prompt_hash}",
        f"# status: {result.ai_status}",
        f"# target module: {result.target_module}",
    ]
    for dropped in result.dropped:
        header.append(f"# dropped {dropped.source_column}: {dropped.reason}")
    body = str(
        yaml.safe_dump(
            [item.model_dump(mode="json") for item in result.suggestions],
            sort_keys=True,
            allow_unicode=True,
        )
    )
    return "\n".join(header) + "\n" + body


__all__: list[str] = [
    "SAMPLE_LIMIT",
    "ColumnSamples",
    "DroppedSuggestion",
    "SuggestMappingResult",
    "SuggestTransformResult",
    "TransformTarget",
    "draft_yaml",
    "guess_transform",
    "heuristic_mapping",
    "mapping_variables",
    "read_column_samples",
    "render_mapping_html",
    "render_mapping_table",
    "render_transform_html",
    "render_transform_table",
    "suggest_mapping",
    "suggest_transform",
    "target_field_lines",
    "validate_mapping",
    "validate_transform",
]
