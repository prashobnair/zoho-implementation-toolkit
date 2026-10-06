"""Mapping eval metrics (AI-MIG-1): precision, recall, abstention, guardrails.

Dataset cases carry source columns (name + 5 synthetic sample values),
target field metadata and a gold mapping. ``case_variables`` renders the
prompt variables; ``validate_response`` enforces the structural guardrails
(coverage, known targets/transforms, evidence indexes, the confidence-0.6
abstention rule); precision/recall/abstention are scored against gold.
``bad_caught`` decides whether a bad recording was rejected, flagged or
fell back as its case expects.
"""

from __future__ import annotations

from typing import Any

from zohokit.ai.schemas import MappingDraft
from zohokit.modules.migration.mapping import TransformError, coerce_transform

#: Confidence below which the suggester must abstain (AI-MIG-1).
ABSTAIN_BELOW = 0.6


def case_variables(case: dict[str, Any]) -> dict[str, str]:
    """Render deterministic prompt variables for a dataset case."""
    column_lines = [
        f"{column['name']}: {' | '.join(column['samples'])}"
        for column in case["input"]["source_columns"]
    ]
    target_lines = []
    for field in case["input"]["target_fields"]:
        line = f"{field['api_name']} ({field['dtype']}, required={field['required']})"
        if field.get("picklist"):
            line += f", values=[{'|'.join(field['picklist'])}]"
        target_lines.append(line)
    return {"source_columns": "\n".join(column_lines), "target_fields": "\n".join(target_lines)}


def gold_map(case: dict[str, Any]) -> dict[str, Any]:
    """Source column name to gold target (None means abstain)."""
    return {entry["source_column"]: entry["target_api_name"] for entry in case["gold"]}


def validate_response(case: dict[str, Any], draft: MappingDraft) -> list[str]:
    """Structural guardrails; value-free violation strings."""
    violations: list[str] = []
    columns = case["input"]["source_columns"]
    names = [column["name"] for column in columns]
    seen: set[str] = set()
    for suggestion in draft.suggestions:
        if suggestion.source_column in seen:
            violations.append("coverage: duplicate suggestion for one column")
        seen.add(suggestion.source_column)
        if suggestion.source_column not in names:
            violations.append("coverage: suggestion for an unknown column")
            continue
        samples = next(
            item["samples"] for item in columns if item["name"] == suggestion.source_column
        )
        for index in suggestion.evidence_samples_idx:
            if not isinstance(index, int) or index < 0 or index >= len(samples):
                violations.append("evidence: sample index out of range")
                break
        known_targets = {field["api_name"] for field in case["input"]["target_fields"]}
        if (
            suggestion.target_api_name is not None
            and suggestion.target_api_name not in known_targets
        ):
            violations.append("reference: unknown target field")
        for entry in suggestion.transform:
            try:
                coerce_transform(entry)
            except TransformError:
                violations.append("reference: unknown transform")
                break
        if suggestion.confidence < ABSTAIN_BELOW and suggestion.target_api_name is not None:
            violations.append("abstention: mapped below the confidence floor")
        if suggestion.transform and suggestion.target_api_name is None:
            violations.append("abstention: abstained entry proposes transforms")
    for name in names:
        if name not in seen:
            violations.append("coverage: source column has no suggestion")
    return violations


def case_scores(case: dict[str, Any], draft: MappingDraft) -> dict[str, int]:
    """Count correct/predicted/gold mappings plus abstention outcomes."""
    gold = gold_map(case)
    by_column = {item.source_column: item for item in draft.suggestions}
    correct = predicted = gold_positive = 0
    abstain_correct = abstain_total = 0
    for column, want in gold.items():
        got_item = by_column.get(column)
        got = got_item.target_api_name if got_item is not None else "missing"
        if want is None:
            abstain_total += 1
            if got is None:
                abstain_correct += 1
        else:
            gold_positive += 1
            if got is not None:
                predicted += 1
                if got == want:
                    correct += 1
    return {
        "correct": correct,
        "predicted": predicted,
        "gold_positive": gold_positive,
        "abstain_correct": abstain_correct,
        "abstain_total": abstain_total,
    }


def good_metrics(totals: dict[str, int]) -> dict[str, float]:
    """Aggregate gated quality metrics over the good split."""
    precision = totals["correct"] / totals["predicted"] if totals["predicted"] else 1.0
    recall = totals["correct"] / totals["gold_positive"] if totals["gold_positive"] else 1.0
    abstention = (
        totals["abstain_correct"] / totals["abstain_total"] if totals["abstain_total"] else 1.0
    )
    return {"precision": precision, "recall": recall, "abstention_rate": abstention}


def case_f1(case: dict[str, Any], draft: MappingDraft) -> float:
    """F1 of one response against gold (bad-set injection tripwire)."""
    scores = case_scores(case, draft)
    precision = scores["correct"] / scores["predicted"] if scores["predicted"] else 0.0
    recall = scores["correct"] / scores["gold_positive"] if scores["gold_positive"] else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def bad_caught(case: dict[str, Any], ai_status: str, draft: MappingDraft | None) -> bool:
    """True when a bad recording met its expected safe outcome."""
    expected = case.get("expected", {}).get("outcome", "rejected")
    if expected == "fallback":
        return ai_status == "fallback"
    if ai_status == "fallback" or draft is None:
        return True
    if validate_response(case, draft):
        return True
    return case_f1(case, draft) < 0.5


__all__: list[str] = [
    "ABSTAIN_BELOW",
    "bad_caught",
    "case_f1",
    "case_scores",
    "case_variables",
    "gold_map",
    "good_metrics",
    "validate_response",
]
