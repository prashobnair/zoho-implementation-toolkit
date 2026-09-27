"""Exit-code tests per STD §3.5."""

from __future__ import annotations

from datetime import UTC, datetime

from zohokit.cli.exitcodes import ExitCode, resolve
from zohokit.core.findings import Report


def _report(*, ready: bool) -> Report:
    now = datetime(2026, 9, 27, tzinfo=UTC)
    return Report.build(
        module="migration",
        run_id="run-1",
        started_at=now,
        finished_at=now,
        findings=[],
        ready=ready,
    )


def test_exit_code_values_match_spec() -> None:
    assert (ExitCode.READY, ExitCode.INPUT_ERROR, ExitCode.BLOCKED) == (0, 1, 2)
    assert (ExitCode.CONNECTOR_ERROR, ExitCode.SAFETY_GUARD) == (3, 4)


def test_strict_not_ready_is_blocked() -> None:
    assert resolve(_report(ready=False), strict=True) is ExitCode.BLOCKED


def test_ready_is_zero_even_strict() -> None:
    assert resolve(_report(ready=True), strict=True) is ExitCode.READY


def test_non_strict_run_exits_zero() -> None:
    assert resolve(_report(ready=False), strict=False) is ExitCode.READY
