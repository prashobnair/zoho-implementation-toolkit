"""Lazy pagination helpers for both Zoho styles (STD-H2).

``page``/``per_page`` and ``page_token`` iterators are lazy generators:
each page costs exactly one call from the :class:`CallBudget`, and when
the budget runs out iteration stops with ``outcome.truncated`` set so the
caller can mark partial results ``truncated: true`` (STD-L5).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from zohokit.connectors.zoho.budget import CallBudget


@dataclass
class PaginationOutcome:
    """Records whether iteration stopped early on the call budget."""

    truncated: bool = False
    pages: int = 0
    items: int = 0


def iter_page_number_pages(
    fetch_page: Callable[[int, int], tuple[list[dict[str, Any]], bool]],
    *,
    budget: CallBudget,
    outcome: PaginationOutcome,
    start_page: int = 1,
    per_page: int = 200,
) -> Iterator[dict[str, Any]]:
    """Yield records for ``page``/``per_page`` APIs.

    *fetch_page* receives ``(page, per_page)`` and returns ``(records,
    more_records)``. Stops with ``outcome.truncated = True`` when the
    budget is exhausted mid-list.
    """
    page = start_page
    while True:
        if not budget.consume():
            outcome.truncated = True
            return
        outcome.pages += 1
        records, more_records = fetch_page(page, per_page)
        outcome.items += len(records)
        yield from records
        if not more_records:
            return
        page += 1


def iter_page_token_pages(
    fetch_page: Callable[[str | None], tuple[list[dict[str, Any]], str | None]],
    *,
    budget: CallBudget,
    outcome: PaginationOutcome,
    start_token: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield records for ``page_token`` APIs (Zoho CRM v8 past the offset).

    *fetch_page* receives the current token (None for the first page) and
    returns ``(records, next_token)``; a None token ends the list. Stops
    with ``outcome.truncated = True`` when the budget is exhausted.
    """
    token = start_token
    while True:
        if not budget.consume():
            outcome.truncated = True
            return
        outcome.pages += 1
        records, next_token = fetch_page(token)
        outcome.items += len(records)
        yield from records
        if next_token is None:
            return
        token = next_token


__all__: list[str] = [
    "PaginationOutcome",
    "iter_page_number_pages",
    "iter_page_token_pages",
]
