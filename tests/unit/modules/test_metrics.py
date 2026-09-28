"""Metrics port tests: TK-FIX-3 duplicates and TK-FIX-4 staff validation."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

from hypothesis import assume, given
from hypothesis import strategies as st

from zohokit.core.context import RunContext
from zohokit.core.findings import Severity
from zohokit.modules.metrics.engine import analyze, run
from zohokit.modules.metrics.models import MetricsInput
from zohokit.modules.metrics.report import to_legacy_dict
from zohokit.reports import render_json

ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _examples() -> MetricsInput:
    path = ROOT / "tests" / "golden" / "legacy" / "metrics" / "inputs" / "examples.json"
    return MetricsInput.model_validate(json.loads(path.read_text()))


def _data() -> dict:
    path = ROOT / "tests" / "golden" / "legacy" / "metrics" / "inputs" / "examples.json"
    return json.loads(path.read_text())


def test_examples_exact_values() -> None:
    analysis = analyze(_examples())
    legacy = to_legacy_dict(analysis)
    assert legacy["metrics"]["paid_net_revenue"] == "1200.00"
    assert legacy["metrics"]["won_deals"] == 1
    assert legacy["findings"] == [
        {"code": "stale_snapshot", "source": "books"},
        {"code": "currency_mismatch", "source": "i-2"},
    ]
    assert legacy["dashboard"] is False


def test_duplicate_deal_excluded_tk_fix_3() -> None:
    """The same won deal twice counts once; excluded_rows counts it."""
    data = _data()
    data["deals"].append(copy.deepcopy(data["deals"][0]))
    analysis = analyze(MetricsInput.model_validate(data))
    legacy = to_legacy_dict(analysis)
    assert legacy["metrics"]["won_deals"] == 1
    assert legacy["metrics"]["won_accounts"] == 1
    assert {"code": "duplicate_id", "source": "d-1"} in legacy["findings"]
    (finding,) = [item for item in analysis.findings if item.code == "duplicate_id"]
    assert finding.severity is Severity.ERROR
    assert finding.evidence["excluded_rows"] == 1


def test_duplicate_invoice_excluded_from_revenue() -> None:
    data = _data()
    data["invoices"].append(copy.deepcopy(data["invoices"][0]))
    analysis = analyze(MetricsInput.model_validate(data))
    legacy = to_legacy_dict(analysis)
    assert legacy["metrics"]["paid_net_revenue"] == "1200.00"
    assert {"code": "duplicate_id", "source": "i-1"} in legacy["findings"]


def test_staff_validation_tk_fix_4() -> None:
    data = _data()
    data["staff"] = [
        {"id": "s-neg", "hours_available": -5, "hours_booked": 0},
        {"id": "s-zero", "hours_available": 0, "hours_booked": 0},
        {"id": "s-over", "hours_available": 40, "hours_booked": 41},
        {"id": "s-under", "hours_available": 40, "hours_booked": -1},
        {"id": "s-text", "hours_available": "forty", "hours_booked": 0},
        {"id": "s-ok", "hours_available": 40, "hours_booked": 20},
    ]
    analysis = analyze(MetricsInput.model_validate(data), audience="operations")
    legacy = to_legacy_dict(analysis)
    invalid = [item for item in legacy["findings"] if item["code"] == "invalid_staff_row"]
    assert [item["source"] for item in invalid] == [
        "s-neg",
        "s-zero",
        "s-over",
        "s-under",
        "s-text",
    ]
    assert legacy["metrics"]["booked_utilization_percent"] == "50.00"
    assert all(finding.severity is Severity.ERROR for finding in analysis.findings)


def test_frozen_clock_byte_identical() -> None:
    inputs = _examples()
    now = datetime(2026, 9, 27, 12, tzinfo=UTC)
    assert render_json(run(inputs, ctx=RunContext(now=now))) == render_json(
        run(inputs, ctx=RunContext(now=now))
    )


def _ids(inputs: MetricsInput, audience: str = "finance") -> list[str]:
    return sorted(finding.id for finding in analyze(inputs, audience=audience).findings)


@given(st.data())
def test_ids_stable_under_row_shuffle(data: st.DataObject) -> None:
    base = _data()
    payload = {
        key: [rows[index] for index in data.draw(st.permutations(range(len(rows))))]
        for key, rows in base.items()
        if isinstance(rows, list)
    }
    payload.update({key: value for key, value in base.items() if not isinstance(value, list)})
    first = _ids(MetricsInput.model_validate(base))
    second = _ids(MetricsInput.model_validate(payload))
    assert first == second


@given(st.text(min_size=1, max_size=8))
def test_ids_stable_when_account_added(extra: str) -> None:
    base = _data()
    assume(extra and extra not in {row.get("id") for row in base["accounts"]})
    before = set(_ids(MetricsInput.model_validate(base)))
    base["accounts"].append({"id": extra, "segment": "SMB"})
    assert before <= set(_ids(MetricsInput.model_validate(base)))


def test_ids_unique() -> None:
    ids = _ids(_examples())
    assert len(ids) == len(set(ids))
