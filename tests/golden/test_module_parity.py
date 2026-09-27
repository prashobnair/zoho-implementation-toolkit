"""WP-06 golden parity: report.to_legacy_dict() vs every golden file (TK-MIG-3).

The only allowed differences are the intentional fixes, each asserted
explicitly with its exact new value (never by editing the goldens):
- TK-FIX-1: release ``target_manifest_sha256`` is order-free now.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from zohokit.modules import Analysis
from zohokit.modules.forms.engine import analyze as analyze_forms
from zohokit.modules.forms.models import FormsInput
from zohokit.modules.forms.report import to_legacy_dict as legacy_forms
from zohokit.modules.migration.engine import analyze as analyze_migration
from zohokit.modules.migration.models import MigrationInput
from zohokit.modules.migration.report import to_legacy_dict as legacy_migration
from zohokit.modules.release.engine import analyze as analyze_release
from zohokit.modules.release.models import ReleaseInput
from zohokit.modules.release.report import to_legacy_dict as legacy_release
from zohokit.modules.workflow.engine import analyze as analyze_workflow
from zohokit.modules.workflow.models import WorkflowInput
from zohokit.modules.workflow.report import to_legacy_dict as legacy_workflow

ROOT = Path(__file__).resolve().parent.parent.parent

PORTS: dict[str, dict[str, Any]] = {
    "migration": {
        "model": MigrationInput,
        "analyze": analyze_migration,
        "to_legacy": legacy_migration,
        "ready_key": "ready_for_import",
    },
    "release": {
        "model": ReleaseInput,
        "analyze": analyze_release,
        "to_legacy": legacy_release,
        "ready_key": "ready_for_release",
    },
    "workflow": {
        "model": WorkflowInput,
        "analyze": analyze_workflow,
        "to_legacy": legacy_workflow,
        "ready_key": None,
    },
    "forms": {
        "model": FormsInput,
        "analyze": analyze_forms,
        "to_legacy": legacy_forms,
        "ready_key": "all_pass",
    },
}

# TK-FIX-1 intentional diffs: order-free fingerprints (old goldens are order-sensitive).
RELEASE_FINGERPRINTS = {
    "01_examples.json": "ca3d3e6e445d337ed25e8e3ac7024741a37bab1a607b345522b6bf7c453bdae5",
    "02_examples_strict.json": "ca3d3e6e445d337ed25e8e3ac7024741a37bab1a607b345522b6bf7c453bdae5",
    "03_no_change.json": "a596a4f120580f514a3ead84452a03a0f208f7f4b4efd91e4351358580d2f26a",
    "04_added_workflow.json": "7ea0a1a48a612145f9868a542a719464e6833afa1076212f048900224163ff73",
    "05_unknown_dependency.json": (
        "f9c8b22f839bfd875e633a8a2060219f2a27f6a662790ea03de50a79c914247f"
    ),
}


def _cases() -> list[tuple[str, dict[str, Any]]]:
    cases: list[tuple[str, dict[str, Any]]] = []
    for module in sorted(PORTS):
        manifest_path = ROOT / "tests" / "golden" / "legacy" / module / "_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest:
            cases.append((module, entry))
    return cases


@pytest.mark.parametrize(("module", "entry"), _cases())
def test_legacy_parity(module: str, entry: dict[str, Any]) -> None:
    """to_legacy_dict() equals the WP-06 golden, modulo intentional fixes."""
    port = PORTS[module]
    inputs = json.loads((ROOT / entry["input"]).read_text(encoding="utf-8"))
    analysis: Analysis = port["analyze"](port["model"].model_validate(inputs))
    actual = port["to_legacy"](analysis)
    golden_name = entry["golden"].split("/")[-1]
    expected = json.loads((ROOT / entry["golden"]).read_text(encoding="utf-8"))
    if module == "release":
        assert actual.pop("target_manifest_sha256") == RELEASE_FINGERPRINTS[golden_name]
        assert expected.pop("target_manifest_sha256") != RELEASE_FINGERPRINTS[golden_name]
    assert actual == expected
    ready_key = port["ready_key"]
    if ready_key is not None:
        assert analysis.ready == expected[ready_key]
