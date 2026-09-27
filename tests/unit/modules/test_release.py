"""Release port tests: exact diff values and TK-FIX-1 at module level."""

from __future__ import annotations

import copy
import itertools
import json
from pathlib import Path

from zohokit.modules.release.engine import analyze
from zohokit.modules.release.models import ReleaseInput
from zohokit.modules.release.report import to_legacy_dict

ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _examples() -> ReleaseInput:
    path = ROOT / "legacy" / "zoho-release-readiness-audit" / "examples.json"
    return ReleaseInput.model_validate(json.loads(path.read_text()))


def test_examples_exact_changes() -> None:
    analysis = analyze(_examples())
    assert analysis.ready is False
    assert analysis.legacy["changes"] == [
        {"kind": "field", "name": "Deal.External_Ref", "change": "removed"},
        {"kind": "function", "name": "Post_Deal", "change": "changed"},
        {"kind": "validation", "name": "Deal.Require_Ref", "change": "changed"},
    ]
    assert analysis.legacy["findings"][0] == {
        "code": "behavior_regression_review",
        "component": "function:Post_Deal",
    }
    assert analysis.legacy["deployment_actions"] == 0


def test_no_change_ready() -> None:
    inputs = _examples()
    unchanged = ReleaseInput(before=inputs.before, after=copy.deepcopy(inputs.before))
    analysis = analyze(unchanged)
    assert analysis.ready is True
    assert analysis.legacy["changes"] == []
    assert to_legacy_dict(analysis)["target_manifest_sha256"] == (
        "a596a4f120580f514a3ead84452a03a0f208f7f4b4efd91e4351358580d2f26a"
    )


def test_fingerprint_ignores_order_tk_fix_1() -> None:
    inputs = _examples()
    expected = to_legacy_dict(analyze(inputs))["target_manifest_sha256"]
    for ordering in itertools.permutations(inputs.after):
        permuted = ReleaseInput(before=inputs.before, after=list(ordering))
        assert to_legacy_dict(analyze(permuted))["target_manifest_sha256"] == expected
