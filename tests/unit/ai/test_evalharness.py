"""Eval-harness unit tests (STD-AI11..13): loaders, thresholds, origin labels."""

from __future__ import annotations

from pathlib import Path

import pytest

from zohokit.ai.evalharness import (
    ORIGIN_LABEL,
    EvalHarnessError,
    check_thresholds,
    load_dataset,
    load_recordings,
    load_thresholds,
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_load_dataset_roundtrip(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "dataset.jsonl",
        '{"case_id": "a", "split": "good"}\n\n{"case_id": "b", "split": "bad"}\n',
    )
    cases = load_dataset(path)
    assert [case["case_id"] for case in cases] == ["a", "b"]


def test_load_dataset_rejects_malformed(tmp_path: Path) -> None:
    with pytest.raises(EvalHarnessError):
        load_dataset(_write(tmp_path / "dataset.jsonl", "not json\n"))
    with pytest.raises(EvalHarnessError):
        load_dataset(_write(tmp_path / "dataset.jsonl", '{"no": "keys"}\n'))
    with pytest.raises(EvalHarnessError):
        load_dataset(tmp_path / "missing.jsonl")


def _recordings_doc(origin: str, case_origin: str | None) -> str:
    import json as _json

    entry: dict[str, str] = {"prompt_hash": "h", "response": "{}"}
    if case_origin is not None:
        entry["origin"] = case_origin
    return _json.dumps({"origin": origin, "cases": {"a": entry}})


def test_load_recordings_requires_origin_labels(tmp_path: Path) -> None:
    good = _write(tmp_path / "recordings.json", _recordings_doc(ORIGIN_LABEL, ORIGIN_LABEL))
    assert load_recordings(good) == {"h": "{}"}
    bad_payloads = [
        '{"cases": {}}',
        _recordings_doc("model output", ORIGIN_LABEL),
        _recordings_doc(ORIGIN_LABEL, None),
        _recordings_doc(ORIGIN_LABEL, "model output"),
        f'{{"origin": "{ORIGIN_LABEL}", "cases": {{}}}}',
    ]
    for bad in bad_payloads:
        with pytest.raises(EvalHarnessError):
            load_recordings(_write(tmp_path / "recordings.json", bad))


def test_load_thresholds_and_check(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "thresholds.toml", "[min]\nprecision = 0.9\n[max]\nhallucinated = 0.0\n"
    )
    minimums, maximums = load_thresholds(path)
    assert minimums == {"precision": 0.9}
    assert check_thresholds({"precision": 0.95, "hallucinated": 0.0}, minimums, maximums) == []
    violations = check_thresholds({"precision": 0.5, "hallucinated": 0.0}, minimums, maximums)
    assert len(violations) == 1 and "precision" in violations[0]
    missing = check_thresholds({"precision": 0.95}, minimums, maximums)
    assert any("hallucinated" in item for item in missing)
    extra = check_thresholds(
        {"precision": 0.95, "hallucinated": 0.0, "surprise": 1.0}, minimums, maximums
    )
    assert any("surprise" in item for item in extra)
    with pytest.raises(EvalHarnessError):
        load_thresholds(_write(tmp_path / "thresholds.toml", "not toml [[[\n"))


def test_origin_label_is_stable() -> None:
    assert ORIGIN_LABEL == "hand-authored synthetic"
