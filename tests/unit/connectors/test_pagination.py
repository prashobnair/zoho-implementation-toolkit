"""STD-H2 + STD-L5: lazy pagination styles that respect the call budget."""

from __future__ import annotations

from typing import Any

from zohokit.connectors.zoho.budget import CallBudget
from zohokit.connectors.zoho.pagination import (
    PaginationOutcome,
    iter_page_number_pages,
    iter_page_token_pages,
)


def test_page_per_page_stops_at_budget_with_truncated() -> None:
    calls = 0

    def fetch(page: int, per_page: int) -> tuple[list[dict[str, Any]], bool]:
        nonlocal calls
        calls += 1
        assert per_page == 200
        return ([{"id": f"r-{page}-{i}"} for i in range(2)], page < 500)

    budget = CallBudget(max_calls=200)
    outcome = PaginationOutcome()
    records = list(iter_page_number_pages(fetch, budget=budget, outcome=outcome, per_page=200))
    assert len(records) == 400
    assert calls == 200
    assert outcome.truncated is True
    assert outcome.pages == 200


def test_page_per_page_completes_when_pages_fit_budget() -> None:
    def fetch(page: int, per_page: int) -> tuple[list[dict[str, Any]], bool]:
        return ([{"id": f"r-{page}"}], page < 3)

    budget = CallBudget(max_calls=200)
    outcome = PaginationOutcome()
    records = list(iter_page_number_pages(fetch, budget=budget, outcome=outcome))
    assert [record["id"] for record in records] == ["r-1", "r-2", "r-3"]
    assert outcome.truncated is False


def test_page_token_style_stops_at_budget_with_truncated() -> None:
    seen: list[str | None] = []

    def fetch(token: str | None) -> tuple[list[dict[str, Any]], str | None]:
        seen.append(token)
        index = 0 if token is None else int(token)
        nxt = None if index + 1 >= 500 else str(index + 1)
        return ([{"id": f"t-{index}"}], nxt)

    budget = CallBudget(max_calls=200)
    outcome = PaginationOutcome()
    records = list(iter_page_token_pages(fetch, budget=budget, outcome=outcome))
    assert len(records) == 200
    assert outcome.truncated is True
    assert outcome.pages == 200
    assert seen[0] is None
    assert seen[1] == "1"


def test_page_token_style_completes() -> None:
    def fetch(token: str | None) -> tuple[list[dict[str, Any]], str | None]:
        if token is None:
            return ([{"id": "a"}], "tok-2")
        return ([{"id": "b"}], None)

    budget = CallBudget(max_calls=200)
    outcome = PaginationOutcome()
    assert [r["id"] for r in iter_page_token_pages(fetch, budget=budget, outcome=outcome)] == [
        "a",
        "b",
    ]
    assert outcome.truncated is False


def test_budget_default_is_200() -> None:
    assert CallBudget().max_calls == 200


def test_iteration_is_lazy_one_call_per_page() -> None:
    calls = 0

    def fetch(page: int, per_page: int) -> tuple[list[dict[str, Any]], bool]:
        nonlocal calls
        calls += 1
        return ([{"id": str(page)}], True)

    budget = CallBudget(max_calls=200)
    outcome = PaginationOutcome()
    iterator = iter_page_number_pages(fetch, budget=budget, outcome=outcome)
    assert calls == 0
    assert next(iterator) == {"id": "1"}
    assert calls == 1
