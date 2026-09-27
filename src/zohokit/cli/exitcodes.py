"""Process exit codes per STD §3.5."""

from __future__ import annotations

from enum import IntEnum

from zohokit.core.findings import Report


class ExitCode(IntEnum):
    """Stable CLI exit codes shared by every module."""

    READY = 0
    INPUT_ERROR = 1
    BLOCKED = 2
    CONNECTOR_ERROR = 3
    SAFETY_GUARD = 4


def resolve(report: Report, *, strict: bool) -> ExitCode:
    """Map a finished report to its exit code.

    Exit 2 only when ``--strict`` is set and blocking findings remain;
    a non-strict run that is not ready still exits 0 (it ran).
    """
    if strict and not report.ready:
        return ExitCode.BLOCKED
    return ExitCode.READY


__all__: list[str] = ["ExitCode", "resolve"]
