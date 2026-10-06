"""Transform eval metrics (AI-MIG-2): 100% sample-parse validation.

Dataset cases carry a column name, sample values (plus sibling columns
when the transform needs them, e.g. a currency column) and a target
type. ``case_variables`` renders the prompt variables exactly the way
the suggester does — values of name-like columns masked to shape hints
(STD-AI8), the column name kept — while validation still applies the
proposal to the original samples. A null proposal is the honest
abstention and must carry low confidence.
"""

from __future__ import annotations

from typing import Any

from zohokit.ai.redaction import mask_column_samples
from zohokit.ai.schemas import TransformDraft
from zohokit.modules.migration.mapping import TransformError, apply_transforms, coerce_transform

#: Confidence below which the suggester must abstain (AI-MIG-2).
ABSTAIN_BELOW = 0.6


def case_variables(case: dict[str, Any]) -> dict[str, str]:
    """Render deterministic prompt variables for a dataset case."""
    column = str(case["input"]["column"])
    return {
        "column": column,
        "samples": "\n".join(mask_column_samples(column, case["input"]["samples"])),
        "target_type": str(case["input"]["target_type"]),
    }


def sample_rows(case: dict[str, Any]) -> list[dict[str, str]]:
    """One row per sample, carrying sibling columns when the case defines them."""
    siblings = case["input"].get("siblings", {})
    rows = []
    for index, sample in enumerate(case["input"]["samples"]):
        row = {key: values[index] for key, values in siblings.items()}
        row["value"] = sample
        rows.append(row)
    return rows


def validate_response(case: dict[str, Any], draft: TransformDraft) -> list[str]:
    """Apply the proposal to every sample; value-free violation strings."""
    violations: list[str] = []
    samples = case["input"]["samples"]
    if draft.transform is None:
        if draft.confidence >= ABSTAIN_BELOW:
            violations.append("abstention: null proposal needs low confidence")
        return violations
    if draft.confidence < ABSTAIN_BELOW:
        violations.append("abstention: proposed transform needs high confidence")
    try:
        spec = coerce_transform(draft.transform)
    except TransformError:
        violations.append("reference: transform does not parse")
        return violations
    for index, row in enumerate(sample_rows(case)):
        try:
            apply_transforms(row.get("value"), row, [spec])
        except TransformError:
            violations.append(f"parse: sample #{index} fails the proposed transform")
            break
    want = set(range(len(samples)))
    if set(draft.evidence_samples_idx) != want:
        violations.append("evidence: must list every checked sample index")
    return violations


def grade_good(case: dict[str, Any], draft: TransformDraft) -> dict[str, bool]:
    """Per-case booleans aggregated by :func:`good_metrics`."""
    is_abstain_case = case["input"].get("expect_abstain", False)
    if is_abstain_case:
        abstention_ok = draft.transform is None and draft.confidence < ABSTAIN_BELOW
        return {"parse_ok": True, "abstention_ok": abstention_ok, "is_abstain_case": True}
    parse_ok = draft.transform is not None and validate_response(case, draft) == []
    return {"parse_ok": parse_ok, "abstention_ok": True, "is_abstain_case": False}


def good_metrics(grades: list[dict[str, bool]]) -> dict[str, float]:
    """Aggregate gated quality metrics over the good split."""
    real = [grade for grade in grades if not grade["is_abstain_case"]]
    abstain_cases = [grade for grade in grades if grade["is_abstain_case"]]
    return {
        "parse_success_rate": (
            sum(1 for grade in real if grade["parse_ok"]) / len(real) if real else 1.0
        ),
        "abstention_rate": (
            sum(1 for grade in abstain_cases if grade["abstention_ok"]) / len(abstain_cases)
            if abstain_cases
            else 1.0
        ),
    }


def bad_caught(case: dict[str, Any], ai_status: str, draft: TransformDraft | None) -> bool:
    """True when a bad recording met its expected safe outcome."""
    expected = case.get("expected", {}).get("outcome", "rejected")
    if expected == "fallback":
        return ai_status == "fallback"
    if ai_status == "fallback" or draft is None:
        return True
    return validate_response(case, draft) != []


__all__: list[str] = [
    "ABSTAIN_BELOW",
    "bad_caught",
    "case_variables",
    "good_metrics",
    "grade_good",
    "sample_rows",
    "validate_response",
]
