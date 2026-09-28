"""Timeline port tests: TK-FIX-6 key and typed-claim normalization."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from hypothesis import assume, given
from hypothesis import strategies as st

from zohokit.core.context import RunContext
from zohokit.modules.timeline.engine import (
    analyze,
    normalize_claim_key,
    normalize_claim_value,
    run,
)
from zohokit.modules.timeline.models import TimelineInput
from zohokit.modules.timeline.report import to_legacy_dict
from zohokit.reports import render_json

ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _event(eid: str, key: str, value: str, claim_type: str | None = None) -> dict:
    claim: dict = {"key": key, "value": value}
    if claim_type is not None:
        claim["type"] = claim_type
    return {
        "id": eid,
        "type": "call",
        "at": "2026-01-05T10:00:00+05:30",
        "source_id": f"source-{eid}",
        "visibility": "client",
        "summary": f"Event {eid}",
        "claim": claim,
    }


def _input(*events: dict) -> TimelineInput:
    return TimelineInput(events=list(events))


def test_key_normalization() -> None:
    assert normalize_claim_key("Launch-Date") == "launch_date"
    assert normalize_claim_key("  launch date  ") == "launch_date"
    assert normalize_claim_key("SEAT_COUNT") == "seat_count"


def test_key_variants_conflict_tk_fix_6() -> None:
    """'Launch-Date' vs 'launch date' share a normalized key and conflict."""
    analysis = analyze(
        _input(
            _event("e-1", "Launch-Date", "2026-03-01"), _event("e-2", "launch date", "2026-04-01")
        )
    )
    assert to_legacy_dict(analysis)["conflicts"] == [
        {"key": "launch_date", "event_ids": ["e-1", "e-2"], "code": "conflicting_claims"}
    ]
    assert analysis.ready is False


def test_typed_date_normalizes_forms() -> None:
    analysis = analyze(
        _input(
            _event("e-1", "Go Live", "2026-02-01", "date"),
            _event("e-2", "go_live", "2026-02-01T00:00:00Z", "date"),
        )
    )
    assert to_legacy_dict(analysis)["conflicts"] == []
    assert analysis.ready is True


def test_untyped_keeps_string_comparison() -> None:
    analysis = analyze(
        _input(
            _event("e-1", "Go Live", "2026-02-01"),
            _event("e-2", "go_live", "2026-02-01T00:00:00Z"),
        )
    )
    assert len(to_legacy_dict(analysis)["conflicts"]) == 1


def test_typed_number_money_text() -> None:
    assert normalize_claim_value("600.00", "number") == "600"
    assert normalize_claim_value("1200.00 INR", "money") == "1200.00 inr"
    assert normalize_claim_value("Go  Live", "text") == "go live"
    assert normalize_claim_value("a  b", None) == "a  b"


def test_typed_number_equal_no_conflict() -> None:
    analysis = analyze(
        _input(
            _event("e-1", "Seats", "60", "number"),
            _event("e-2", "seats", "60.00", "number"),
        )
    )
    assert to_legacy_dict(analysis)["conflicts"] == []


def test_examples_conflict_exact() -> None:
    path = ROOT / "legacy" / "zoho-client-timeline-composer" / "examples.json"
    inputs = TimelineInput.model_validate(json.loads(path.read_text()))
    analysis = analyze(inputs)
    assert to_legacy_dict(analysis)["conflicts"] == [
        {"key": "launch_date", "event_ids": ["call-1", "email-1"], "code": "conflicting_claims"}
    ]
    assert [event["id"] for event in to_legacy_dict(analysis)["timeline"]] == [
        "call-1",
        "email-1",
        "deal-1",
        "milestone-1",
    ]


def test_frozen_clock_byte_identical() -> None:
    path = ROOT / "legacy" / "zoho-client-timeline-composer" / "examples.json"
    inputs = TimelineInput.model_validate(json.loads(path.read_text()))
    now = datetime(2026, 9, 27, 12, tzinfo=UTC)
    assert render_json(run(inputs, ctx=RunContext(now=now))) == render_json(
        run(inputs, ctx=RunContext(now=now))
    )


def _examples_input() -> TimelineInput:
    path = ROOT / "legacy" / "zoho-client-timeline-composer" / "examples.json"
    return TimelineInput.model_validate(json.loads(path.read_text()))


def _ids(inputs: TimelineInput) -> list[str]:
    return sorted(finding.id for finding in analyze(inputs).findings)


@given(st.data())
def test_ids_stable_under_event_shuffle(data: st.DataObject) -> None:
    inputs = _examples_input()
    order = data.draw(st.permutations(range(len(inputs.events))))
    shuffled = TimelineInput(events=[inputs.events[index] for index in order])
    assert _ids(shuffled) == _ids(inputs)


@given(st.text(min_size=1, max_size=8))
def test_ids_stable_when_event_added(extra: str) -> None:
    inputs = _examples_input()
    ids = {event.get("id") for event in inputs.events}
    fresh = extra.strip()
    assume(fresh and fresh not in ids)
    before = set(_ids(inputs))
    extended = TimelineInput(
        events=[
            *inputs.events,
            {
                "id": fresh,
                "type": "call",
                "at": "2026-02-01T10:00:00Z",
                "source_id": "source-extra",
                "visibility": "client",
                "summary": "Extra call without claims",
            },
        ]
    )
    assert before <= set(_ids(extended))


def test_ids_unique() -> None:
    ids = _ids(_examples_input())
    assert len(ids) == len(set(ids)) == 1
