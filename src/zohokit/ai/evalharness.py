"""Eval harness: datasets, hand-authored recordings, thresholds (STD-AI11..13).

Each ``evals/<feature>/`` directory holds ``dataset.jsonl`` (synthetic
cases), ``recordings/recordings.json`` (hand-authored synthetic provider
responses keyed by prompt hash, never model outputs), ``metrics.py``
(feature-appropriate pure functions), ``thresholds.toml`` (CI gates) and
``REPORT.md`` (model, date, both metric sets, cost).

Every dataset ships two case sets: ``good`` cases measuring quality
against the spec thresholds, and ``bad`` cases carrying deliberately
wrong recordings (bad citations, hallucinated numbers, malformed JSON,
injection inputs, unmappable columns) that the validators must catch.
Guardrail catch rate on the bad set must be 100%.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from zohokit.ai.providers import AiError

#: Label every recording file and every eval REPORT must carry.
ORIGIN_LABEL = "hand-authored synthetic"


class EvalHarnessError(AiError):
    """An eval bundle is malformed (file + reason only, never case data)."""


def load_dataset(path: str | Path) -> list[dict[str, Any]]:
    """Read a ``dataset.jsonl`` file (one JSON object per line)."""
    text_path = Path(path)
    try:
        lines = text_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        raise EvalHarnessError(f"eval dataset missing: {text_path.name}") from None
    cases: list[dict[str, Any]] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            raise EvalHarnessError(f"eval dataset {text_path.name} line {lineno} invalid") from None
        if not isinstance(item, dict) or "case_id" not in item or "split" not in item:
            raise EvalHarnessError(
                f"eval dataset {text_path.name} line {lineno} misses case_id/split"
            ) from None
        cases.append(item)
    return cases


def load_recordings(path: str | Path) -> dict[str, str]:
    """Read ``recordings.json`` and return prompt-hash → raw response.

    Every recording file must declare ``"origin": "hand-authored
    synthetic"``; every case entry carries its own origin label plus the
    prompt hash it answers, so a stale entry (hash mismatch) fails loudly
    instead of grading the wrong prompt.
    """
    text_path = Path(path)
    try:
        bundle = json.loads(text_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise EvalHarnessError(f"eval recordings unreadable: {text_path.name}") from None
    if not isinstance(bundle, dict) or bundle.get("origin") != ORIGIN_LABEL:
        raise EvalHarnessError(f"eval recordings {text_path.name} miss the origin label") from None
    cases = bundle.get("cases")
    if not isinstance(cases, dict) or not cases:
        raise EvalHarnessError(f"eval recordings {text_path.name} carry no cases") from None
    out: dict[str, str] = {}
    for _case_id, entry in cases.items():
        if not isinstance(entry, dict):
            raise EvalHarnessError(f"eval recordings {text_path.name} case entry invalid") from None
        if entry.get("origin") != ORIGIN_LABEL:
            raise EvalHarnessError(
                f"eval recordings {text_path.name} case entry misses the origin label"
            ) from None
        prompt_hash = entry.get("prompt_hash")
        raw = entry.get("response")
        if not isinstance(prompt_hash, str) or not prompt_hash:
            raise EvalHarnessError(
                f"eval recordings {text_path.name} case entry misses prompt_hash"
            ) from None
        if not isinstance(raw, str) or not raw:
            raise EvalHarnessError(
                f"eval recordings {text_path.name} case entry misses response"
            ) from None
        if prompt_hash in out:
            raise EvalHarnessError(
                f"eval recordings {text_path.name} reuse prompt hash twice"
            ) from None
        out[prompt_hash] = raw
    return out


def load_thresholds(path: str | Path) -> tuple[dict[str, float], dict[str, float]]:
    """Read ``thresholds.toml`` → (minimums, maximums) per metric."""
    text_path = Path(path)
    try:
        data = tomllib.loads(text_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise EvalHarnessError(f"eval thresholds unreadable: {text_path.name}") from None
    minimums = data.get("min", {})
    maximums = data.get("max", {})
    if not isinstance(minimums, dict) or not isinstance(maximums, dict):
        raise EvalHarnessError(
            f"eval thresholds {text_path.name} need [min]/[max] tables"
        ) from None
    try:
        mins = {str(k): float(v) for k, v in minimums.items()}
        maxs = {str(k): float(v) for k, v in maximums.items()}
    except (TypeError, ValueError):
        raise EvalHarnessError(
            f"eval thresholds {text_path.name} carry non-numeric values"
        ) from None
    return mins, maxs


def check_thresholds(
    metrics: dict[str, float], minimums: dict[str, float], maximums: dict[str, float]
) -> list[str]:
    """Compare metrics against thresholds; return violation strings.

    Metric values are aggregates (rates, counts), never report data, so
    they are safe to print in CI logs.
    """
    violations: list[str] = []
    for name, floor in minimums.items():
        value = metrics.get(name)
        if value is None:
            violations.append(f"metric {name} missing (needs >= {floor})")
        elif value < floor:
            violations.append(f"metric {name} {value:.4f} below threshold {floor}")
    for name, ceiling in maximums.items():
        value = metrics.get(name)
        if value is None:
            violations.append(f"metric {name} missing (needs <= {ceiling})")
        elif value > ceiling:
            violations.append(f"metric {name} {value:.4f} above threshold {ceiling}")
    for name in metrics:
        if name not in minimums and name not in maximums:
            violations.append(f"metric {name} has no threshold")
    return violations


__all__: list[str] = [
    "ORIGIN_LABEL",
    "EvalHarnessError",
    "check_thresholds",
    "load_dataset",
    "load_recordings",
    "load_thresholds",
]
