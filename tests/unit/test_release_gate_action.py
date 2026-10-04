"""Release-gate action hardening: no script injection, PR guard present.

Parses ``action/release-gate/action.yml`` and fails closed on regressions:

- no ``run:`` script may contain a ``${{ }}`` expression (every input and
  step output must travel through ``env:`` and be referenced as a quoted
  shell variable);
- the optional baseline flag must be built as a bash array (no unquoted
  word-splitting);
- ``before``/``after``/``baseline`` values starting with ``-`` are refused
  and ``fail-on`` is validated against its allowlist before use;
- the sticky-comment step must skip with a notice when the action runs
  outside a pull request instead of crashing on
  ``context.payload.pull_request``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ACTION = Path(__file__).resolve().parent.parent.parent / "action" / "release-gate" / "action.yml"

ALLOWED_FAIL_ON = ("error", "high", "medium", "never")


def _load() -> dict[str, object]:
    return yaml.safe_load(ACTION.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _steps() -> list[dict[str, object]]:
    document = _load()
    runs = document["runs"]  # type: ignore[index]
    assert isinstance(runs, dict)
    steps = runs["steps"]
    assert isinstance(steps, list)
    return steps  # type: ignore[no-any-return]


def _run_steps() -> list[dict[str, object]]:
    return [step for step in _steps() if isinstance(step.get("run"), str)]


def _script_steps() -> list[dict[str, object]]:
    return [step for step in _steps() if isinstance(step.get("with"), dict)]


def test_no_interpolation_inside_run_blocks() -> None:
    """Every ``run:`` script must be free of ``${{ }}`` (env: only)."""
    offenders = [
        str(step.get("name", step.get("id", "?")))
        for step in _run_steps()
        if "${{" in str(step["run"])
    ]
    assert offenders == [], f"run: blocks interpolate expressions: {offenders}"


def test_run_inputs_arrive_through_env() -> None:
    """Inputs and step outputs reach bash via ``env:``, quoted at use."""
    by_id = {str(step.get("id", step.get("name"))): step for step in _steps()}
    gate = by_id["gate"]
    assert isinstance(gate.get("env"), dict)
    assert set(gate["env"]) >= {"BEFORE", "AFTER", "BASELINE"}
    gate_run = str(gate["run"])
    assert '"$BEFORE"' in gate_run
    assert '"$AFTER"' in gate_run
    enforce = next(step for step in _run_steps() if step.get("name") == "Enforce the gate")
    assert isinstance(enforce.get("env"), dict)
    assert set(enforce["env"]) >= {"READY", "RISK", "FAIL_ON"}
    enforce_run = str(enforce["run"])
    assert '"$READY"' in enforce_run
    assert '"$RISK"' in enforce_run
    assert '"$FAIL_ON"' in enforce_run


def test_baseline_uses_quoted_array() -> None:
    """The optional baseline flag is a bash array, never word-split."""
    gate_run = str(next(step for step in _run_steps() if step.get("id") == "gate")["run"])
    assert "BASELINE_ARGS=()" in gate_run
    assert '"${BASELINE_ARGS[@]}"' in gate_run
    assert "BASELINE_FLAG" not in gate_run
    assert "SC2086" not in gate_run


def test_flag_like_values_rejected_and_fail_on_validated() -> None:
    """``-*`` before/after/baseline values are refused; fail-on allowlisted."""
    gate_run = str(next(step for step in _run_steps() if step.get("id") == "gate")["run"])
    assert "-*)" in gate_run
    enforce_run = str(
        next(step for step in _run_steps() if step.get("name") == "Enforce the gate")["run"]
    )
    assert "error|high|medium|never" in enforce_run
    for level in ALLOWED_FAIL_ON:
        assert level in enforce_run


def test_comment_step_skips_outside_pull_requests() -> None:
    """The sticky comment is skipped with a notice when there is no PR.

    Documents the guard contract: the github-script must check
    ``context.payload.pull_request`` first and return early (``core.notice``)
    so non-PR runs (push, schedule, workflow_dispatch on main) never crash
    on ``.number`` of ``undefined``.
    """
    scripts = [
        str(step["with"]["script"])  # type: ignore[index]
        for step in _script_steps()
        if isinstance(step.get("with"), dict) and "script" in step["with"]
    ]
    assert scripts, "expected a github-script step"
    script = scripts[0]
    assert "context.payload.pull_request" in script
    assert "core.notice" in script
    guard = script.index("if (!context.payload.pull_request)")
    assert script.index("return;") > guard
    assert script.index("pull_request.number") > guard
