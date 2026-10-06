"""Recorded eval suites (STD-AI11..13): replay hand-authored recordings, gate metrics.

Every recording is hand-authored synthetic data (never a model output);
only ``FakeProvider`` replays them, so these tests never touch the
network. Each feature reports two metric sets: quality on the good
split (gated by ``thresholds.toml``) and guardrail catch rate on the
bad split (must be 100%).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from zohokit.ai.evalharness import (
    ORIGIN_LABEL,
    check_thresholds,
    load_dataset,
    load_recordings,
    load_thresholds,
)
from zohokit.ai.models import AiConfig
from zohokit.ai.pipeline import AiRequest, run_ai
from zohokit.ai.prompts import load_template
from zohokit.ai.providers import FakeProvider
from zohokit.ai.redaction import build_prompt
from zohokit.ai.schemas import ExplainDraft, MappingDraft, TransformDraft
from zohokit.core.redact import Redactor

pytestmark = pytest.mark.eval

ROOT = Path(__file__).resolve().parent.parent.parent
EVALS = ROOT / "evals"


def _load_metrics_module(feature: str) -> Any:
    path = EVALS / feature / "metrics.py"
    spec = importlib.util.spec_from_file_location(f"eval_{feature}_metrics", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


explain_metrics = _load_metrics_module("explain")
mapping_metrics = _load_metrics_module("mapping")
transform_metrics = _load_metrics_module("transform")

FEATURES: dict[str, dict[str, Any]] = {
    "explain": {"schema": ExplainDraft, "metrics": explain_metrics},
    "mapping": {"schema": MappingDraft, "metrics": mapping_metrics},
    "transform": {"schema": TransformDraft, "metrics": transform_metrics},
}


def _load_feature(feature: str) -> tuple[list[dict[str, Any]], dict[str, str], Any]:
    feature_dir = EVALS / feature
    cases = load_dataset(feature_dir / "dataset.jsonl")
    recordings = load_recordings(feature_dir / "recordings" / "recordings.json")
    metrics = FEATURES[feature]["metrics"]
    return cases, recordings, metrics


def _replay(feature: str, case: dict[str, Any], recordings: dict[str, str]) -> Any:
    metrics = FEATURES[feature]["metrics"]
    template = load_template(feature)
    variables = metrics.case_variables(case)
    prompt = build_prompt(template, variables, redactor=Redactor())
    raw = recordings[prompt.prompt_hash]
    provider = FakeProvider({prompt.prompt_hash: raw}, model="eval-fake")
    outcome = run_ai(
        provider,
        AiRequest(template=template, variables=variables),
        FEATURES[feature]["schema"],
        fallback=FEATURES[feature]["schema"],
    )
    return outcome, raw


def _split_cases(cases: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    good = [case for case in cases if case["split"] == "good"]
    bad = [case for case in cases if case["split"] == "bad"]
    assert good and bad, "each eval needs a good split and a bad split"
    return good, bad


def _good_metrics(feature: str, cases: list[dict[str, Any]]) -> dict[str, float]:
    metrics = FEATURES[feature]["metrics"]
    if feature == "explain":
        grades = []
        for case in cases:
            outcome, raw = _replay(feature, case, _recordings(feature))
            assert outcome.ai_status == "ok", case["case_id"]
            grades.append(metrics.grade_good(case, outcome.data, raw))
        return metrics.good_metrics(grades)
    if feature == "mapping":
        totals = {
            "correct": 0,
            "predicted": 0,
            "gold_positive": 0,
            "abstain_correct": 0,
            "abstain_total": 0,
        }
        for case in cases:
            outcome, _raw = _replay(feature, case, _recordings(feature))
            assert outcome.ai_status == "ok", case["case_id"]
            assert metrics.validate_response(case, outcome.data) == [], case["case_id"]
            for key, value in metrics.case_scores(case, outcome.data).items():
                totals[key] += value
        return metrics.good_metrics(totals)
    grades = []
    for case in cases:
        outcome, _raw = _replay(feature, case, _recordings(feature))
        assert outcome.ai_status == "ok", case["case_id"]
        grades.append(metrics.grade_good(case, outcome.data))
    return metrics.good_metrics(grades)


def _catch_rate(feature: str, cases: list[dict[str, Any]]) -> tuple[float, list[str]]:
    metrics = FEATURES[feature]["metrics"]
    missed = []
    for case in cases:
        outcome, raw = _replay(feature, case, _recordings(feature))
        draft = outcome.data if outcome.ai_status not in ("fallback", "disabled") else None
        if feature == "explain":
            caught = metrics.bad_caught(case, outcome.ai_status, draft, raw)
        else:
            caught = metrics.bad_caught(case, outcome.ai_status, draft)
        if not caught:
            missed.append(case["case_id"])
    rate = (len(cases) - len(missed)) / len(cases)
    return rate, missed


_RECORDINGS: dict[str, dict[str, str]] = {}


def _recordings(feature: str) -> dict[str, str]:
    if feature not in _RECORDINGS:
        _RECORDINGS[feature] = load_recordings(EVALS / feature / "recordings" / "recordings.json")
    return _RECORDINGS[feature]


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_good_recordings_meet_thresholds(feature: str) -> None:
    cases, _, _ = _load_feature(feature)
    good, bad = _split_cases(cases)
    minimums, maximums = load_thresholds(EVALS / feature / "thresholds.toml")
    metrics = _good_metrics(feature, good)
    rate, _ = _catch_rate(feature, bad)
    metrics["catch_rate"] = rate
    assert check_thresholds(metrics, minimums, maximums) == []


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_bad_recordings_are_all_caught(feature: str) -> None:
    cases, _, _ = _load_feature(feature)
    _, bad = _split_cases(cases)
    rate, missed = _catch_rate(feature, bad)
    assert missed == [], f"guardrails missed: {missed}"
    assert rate == 1.0


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_every_case_prompt_has_a_recording(feature: str) -> None:
    """Recordings stay keyed by prompt hash: re-render and look up."""
    cases, recordings, metrics = _load_feature(feature)
    template = load_template(feature)
    for case in cases:
        prompt = build_prompt(template, metrics.case_variables(case), redactor=Redactor())
        assert prompt.prompt_hash in recordings, case["case_id"]


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_no_provider_means_disabled(feature: str) -> None:
    """STD-AI4: with no provider configured the deterministic path runs."""
    cases, _, metrics = _load_feature(feature)
    good, _ = _split_cases(cases)
    template = load_template(feature)
    outcome = run_ai(
        None,
        AiRequest(template=template, variables=metrics.case_variables(good[0])),
        FEATURES[feature]["schema"],
        fallback=FEATURES[feature]["schema"],
    )
    assert outcome.ai_status == "disabled"
    assert AiConfig.from_env({}).is_configured is False


def _generator_builders() -> dict[str, Any]:
    path = ROOT / "scripts" / "gen_ai_evals.py"
    spec = importlib.util.spec_from_file_location("gen_ai_evals", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {
        "explain": module.build_explain,
        "mapping": module.build_mapping,
        "transform": module.build_transform,
    }


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_committed_bundles_match_the_generator(feature: str) -> None:
    """Regenerating in memory must equal what is committed (determinism)."""
    builders = _generator_builders()
    metrics = FEATURES[feature]["metrics"]
    cases, responses = builders[feature]()
    dataset_text = "\n".join(json.dumps(case, sort_keys=True) for case in cases) + "\n"
    assert (EVALS / feature / "dataset.jsonl").read_text(encoding="utf-8") == dataset_text
    recording_cases = {}
    for case in cases:
        prompt_hash = build_prompt(
            load_template(feature), metrics.case_variables(case), redactor=Redactor()
        ).prompt_hash
        recording_cases[case["case_id"]] = {
            "origin": ORIGIN_LABEL,
            "prompt_hash": prompt_hash,
            "response": responses[case["case_id"]],
        }
    expected = (
        json.dumps({"origin": ORIGIN_LABEL, "cases": recording_cases}, indent=2, sort_keys=True)
        + "\n"
    )
    actual = (EVALS / feature / "recordings" / "recordings.json").read_text(encoding="utf-8")
    assert actual == expected


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_eval_report_is_current(feature: str) -> None:
    """REPORT.md carries the origin label and the measured metric values."""
    cases, _, _ = _load_feature(feature)
    good, bad = _split_cases(cases)
    metrics = dict(_good_metrics(feature, good))
    rate, _ = _catch_rate(feature, bad)
    metrics["catch_rate"] = rate
    report = (EVALS / feature / "REPORT.md").read_text(encoding="utf-8")
    assert ORIGIN_LABEL in report
    for name, value in metrics.items():
        assert name in report, f"{feature} REPORT.md misses metric {name}"
        assert f"{value:.4f}" in report, f"{feature} REPORT.md misses value of {name}"
