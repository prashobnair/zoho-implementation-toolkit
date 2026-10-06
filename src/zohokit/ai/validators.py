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

# --- STD-AI7: English number words -------------------------------------------
#
# Design choice (documented here so authors know the rule): number words in a
# narrative are CONVERTED to digits and compared against the same digit
# set as numeric tokens, instead of being rejected outright. So "six
# errors" is accepted against a report with 6 errors, while "seven
# errors" is rejected there. Rationale: authors restating a grounded
# count in words ("two contacts" for a report with 2) stay passing, and
# only genuinely ungrounded quantities fail — fail-closed either way.
#
# Vocabulary: zero..nineteen, tens (twenty..ninety), hundred /
# thousand / lakh / crore / million / billion, "a dozen" / "dozen",
# "half", "twice", and the ordinal words first..tenth. Multi-word
# phrases accumulate ("twenty one" -> 21, "one hundred twenty three" ->
# 123, "two dozen" -> 24, "a hundred" -> 100); "and" is filler inside a
# phrase ("one hundred and three" -> 103). A bare "a"/"an" is NOT a
# number ("a gap of 2000" contributes only 2000); it counts as one only
# directly before a scale word ("a hundred", "a dozen").
_NUMBER_WORD_ONES: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_NUMBER_WORD_TENS: dict[str, int] = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_NUMBER_WORD_SCALES: dict[str, int] = {
    "hundred": 100,
    "thousand": 1000,
    "lakh": 100000,
    "million": 1000000,
    "crore": 10000000,
    "billion": 1000000000,
    "dozen": 12,
}
_NUMBER_WORD_ORDINALS: dict[str, int] = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
}
_NUMBER_WORD_TOKENS = (
    frozenset(_NUMBER_WORD_ONES)
    | frozenset(_NUMBER_WORD_TENS)
    | frozenset(_NUMBER_WORD_SCALES)
    | frozenset(_NUMBER_WORD_ORDINALS)
    | frozenset({"half", "twice"})
)
_WORD_TOKEN_RE = re.compile(r"[A-Za-z]+")


def _parse_number_phrase(tokens: list[str], start: int) -> tuple[float | None, int]:
    """Parse one number-word phrase at ``tokens[start]``.

    Returns ``(value, consumed)``; ``consumed`` is 0 when no phrase
    starts here. Matching is full-token and case-folded by the caller,
    so "someone"/"money"/"Won" never read as number words.
    """
    index = start
    total = 0.0
    current = 0.0
    used_number = False
    after_scale = False
    # A leading "a"/"an"/"one" counts as one only before a scale word
    # ("a hundred", "a dozen") or "half" ("a half" is half, not one).
    if tokens[index] in ("a", "an"):
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        if following in _NUMBER_WORD_SCALES or following == "hundred":
            current = 1.0
            used_number = True
            index += 1
        elif following == "half":
            return 0.5, 2
        else:
            return None, 0
    elif tokens[index] == "one" and index + 1 < len(tokens) and tokens[index + 1] == "half":
        return 0.5, 2
    if index < len(tokens) and tokens[index] == "twice" and not used_number:
        return 2.0, 1
    if index < len(tokens) and tokens[index] == "half" and not used_number:
        return 0.5, 1
    while index < len(tokens):
        word = tokens[index]
        # "and" is filler only directly after a scale word ("one hundred
        # and three"); an ordinal/cardinal list ("first and second") stays
        # two separate claims so each is grounded on its own.
        if word == "and" and after_scale:
            following = tokens[index + 1] if index + 1 < len(tokens) else ""
            if following in _NUMBER_WORD_TOKENS:
                index += 1
                after_scale = False
                continue
            break
        if word in _NUMBER_WORD_ONES and 1 <= _NUMBER_WORD_ONES[word] <= 9:
            # Small ones (and, below, ordinals) combine onto a round
            # tens/hundreds ("twenty one", "one hundred five", "twenty
            # first"), start a phrase ("six"), or continue after a
            # flushed scale ("two thousand five"). Anywhere else they
            # start a new claim.
            if current != 0 and current % 10 != 0:
                break
            current += _NUMBER_WORD_ONES[word]
            used_number = True
            after_scale = False
        elif word in _NUMBER_WORD_ORDINALS:
            if current != 0 and current % 10 != 0:
                break
            current += _NUMBER_WORD_ORDINALS[word]
            used_number = True
            after_scale = False
        elif word in _NUMBER_WORD_ONES:
            # Teens ("ten".."nineteen") and "zero" never merge into a
            # running total ("nine nineteen" is 9 and 19): each is its
            # own claim, except onto round hundreds ("one hundred
            # twelve") or after a flushed scale ("one thousand twelve").
            value = _NUMBER_WORD_ONES[word]
            if value == 0:
                if used_number and (current != 0 or total != 0):
                    break
                used_number = True
                after_scale = False
            elif current == 0 or (current > 0 and current % 100 == 0):
                current += value
                used_number = True
                after_scale = False
            else:
                break
        elif word in _NUMBER_WORD_TENS:
            # Tens start a phrase, continue after a flushed scale ("one
            # thousand twenty"), or combine onto round hundreds ("one
            # hundred twenty"). A list ("thirty-five, ninety") stays
            # separate claims.
            if current == 0 or (current > 0 and current % 100 == 0):
                current += _NUMBER_WORD_TENS[word]
                used_number = True
                after_scale = False
            else:
                break
        elif word == "hundred" or word == "dozen":
            current = (current if current else 1.0) * _NUMBER_WORD_SCALES[word]
            used_number = True
            after_scale = word == "hundred"
        elif word in _NUMBER_WORD_SCALES:
            current = (current if current else 1.0) * _NUMBER_WORD_SCALES[word]
            total += current
            current = 0.0
            used_number = True
            after_scale = True
        elif word == "half":
            current = (current if current else 1.0) * 0.5
            used_number = True
            after_scale = False
        elif word == "twice":
            break
        else:
            break
        index += 1
    if not used_number:
        return None, 0
    return total + current, index - start


def _canonical_number(value: float) -> str:
    """Render a parsed number-word value the way digits normalize."""
    if value.is_integer():
        return str(int(value))
    return str(value)


def extract_number_words(text: str) -> set[str]:
    """English number-word values in *text*, converted to digit strings.

    "seven errors" -> {"7"}; "twenty one" -> {"21"}; "a dozen" ->
    {"12"}; "twice" -> {"2"}; "half" -> {"0.5"}; "sixth" -> {"6"}.
    """
    tokens = [match.group(0).casefold() for match in _WORD_TOKEN_RE.finditer(text)]
    found: set[str] = set()
    index = 0
    while index < len(tokens):
        value, consumed = _parse_number_phrase(tokens, index)
        if consumed and value is not None:
            found.add(_canonical_number(value))
            index += consumed
        else:
            index += 1
    return found


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
    """Collect the numbers and dates a narrative is allowed to restate.

    The number set holds digit tokens plus number-word values converted
    to digits, so a report mentioning "one normalized email" licenses a
    narrative saying "1 contact" (and vice versa).
    """
    digits = extract_numbers(report_text)
    words = extract_number_words(report_text)
    return NumberDateSets(
        numbers=frozenset(digits | words),
        dates=frozenset(extract_dates(report_text)),
    )


def check_grounded(
    *,
    narrative: str,
    allowed: NumberDateSets,
) -> GroundingCheck:
    """Verify every number/date in *narrative* appears in the report.

    Both digit tokens ("7 errors") and English number words ("seven
    errors", "a dozen", "twice", "sixth") are checked after conversion
    to digits, so spelling a hallucinated count out in words does not
    bypass the check (STD-AI7). A mismatch names the offending token
    index only, never the value, so the check itself cannot leak report
    data into logs.
    """
    errors: list[str] = []
    narrative_numbers = sorted(extract_numbers(narrative))
    for index, _token in enumerate(narrative_numbers):
        if narrative_numbers[index] not in allowed.numbers:
            errors.append(f"number token #{index} not present in report")
    narrative_words = sorted(extract_number_words(narrative))
    for index, _token in enumerate(narrative_words):
        if narrative_words[index] not in allowed.numbers:
            errors.append(f"number-word token #{index} not present in report")
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
    "extract_number_words",
    "extract_numbers",
    "extract_report_tokens",
]
