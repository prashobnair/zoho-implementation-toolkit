"""Standalone validators: citations (STD-AI6) and number/date grounding (STD-AI7).

Both are pure functions over strings, unit-tested directly and reused by
every AI feature. Failure details are value-free: indexes, lengths and
counts only, never the quoted text or numbers themselves (which may carry
report data).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?\b")
_LONG_DATE_RE = re.compile(
    r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CitationCheck:
    """Outcome of :func:`check_citations`."""

    ok: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class GroundingCheck:
    """Outcome of :func:`check_grounded`."""

    ok: bool
    errors: tuple[str, ...] = ()


def check_citations(
    *,
    cited_ids: list[str],
    quotes: list[str],
    valid_ids: set[str],
    source_text: str,
) -> CitationCheck:
    """Verify every cited ID exists and every quote appears verbatim.

    ``cited_ids`` are finding IDs (or source-span IDs) the output claims;
    ``quotes`` are verbatim excerpts it reproduces; ``source_text`` is the
    input the output was built from. Errors name indexes and lengths only.
    """
    errors: list[str] = []
    for index, cited in enumerate(cited_ids):
        if cited not in valid_ids:
            errors.append(f"cited id #{index} is not a finding of this report")
    for index, quote in enumerate(quotes):
        if not quote:
            errors.append(f"quote #{index} is empty")
        elif quote not in source_text:
            errors.append(f"quote #{index} (len {len(quote)}) not found verbatim in source")
    return CitationCheck(ok=not errors, errors=tuple(errors))


def extract_numbers(text: str) -> set[str]:
    """Number tokens in *text*, normalized (commas stripped)."""
    return {match.group(0).replace(",", "") for match in _NUMBER_RE.finditer(text)}


def extract_dates(text: str) -> set[str]:
    """ISO and long-form date tokens in *text*."""
    found = {match.group(0) for match in _ISO_DATE_RE.finditer(text)}
    found |= {match.group(0) for match in _LONG_DATE_RE.finditer(text)}
    return found


@dataclass(frozen=True)
class NumberDateSets:
    """Extracted report tokens an AI narrative may reuse."""

    numbers: frozenset[str] = field(default_factory=frozenset)
    dates: frozenset[str] = field(default_factory=frozenset)


def extract_report_tokens(report_text: str) -> NumberDateSets:
    """Collect the numbers and dates a narrative is allowed to restate."""
    return NumberDateSets(
        numbers=frozenset(extract_numbers(report_text)),
        dates=frozenset(extract_dates(report_text)),
    )


def check_grounded(
    *,
    narrative: str,
    allowed: NumberDateSets,
) -> GroundingCheck:
    """Verify every number/date in *narrative* appears in the report.

    A mismatch names the offending token index only, never the value, so
    the check itself cannot leak report data into logs (STD-AI7).
    """
    errors: list[str] = []
    narrative_numbers = sorted(extract_numbers(narrative))
    for index, _token in enumerate(narrative_numbers):
        if narrative_numbers[index] not in allowed.numbers:
            errors.append(f"number token #{index} not present in report")
    narrative_dates = sorted(extract_dates(narrative))
    for index, _token in enumerate(narrative_dates):
        if narrative_dates[index] not in allowed.dates:
            errors.append(f"date token #{index} not present in report")
    return GroundingCheck(ok=not errors, errors=tuple(errors))


__all__: list[str] = [
    "CitationCheck",
    "GroundingCheck",
    "NumberDateSets",
    "check_citations",
    "check_grounded",
    "extract_dates",
    "extract_numbers",
    "extract_report_tokens",
]
