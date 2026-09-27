"""Guard for the WP-06 exit criterion: 8 golden folders, >=3 files each (TK-MIG-2)."""

from __future__ import annotations

import json
from pathlib import Path

GOLDEN_ROOT = Path(__file__).parent / "legacy"
EXPECTED_MODULES = {
    "migration",
    "release",
    "workflow",
    "forms",
    "books",
    "metrics",
    "timeline",
    "lead_routing",
}


def test_golden_folders_present() -> None:
    assert {path.name for path in GOLDEN_ROOT.iterdir() if path.is_dir()} == EXPECTED_MODULES


def test_each_folder_has_at_least_three_goldens() -> None:
    for module in sorted(EXPECTED_MODULES):
        goldens = [
            path for path in (GOLDEN_ROOT / module).glob("*.json") if path.name != "_manifest.json"
        ]
        assert len(goldens) >= 3, f"{module} has {len(goldens)} goldens"
        for golden in goldens:
            json.loads(golden.read_text(encoding="utf-8"))


def test_manifest_covers_every_golden() -> None:
    for module in sorted(EXPECTED_MODULES):
        folder = GOLDEN_ROOT / module
        manifest = json.loads((folder / "_manifest.json").read_text(encoding="utf-8"))
        listed = {entry["golden"] for entry in manifest}
        on_disk = {
            f"tests/golden/legacy/{module}/{path.name}"
            for path in folder.glob("*.json")
            if path.name != "_manifest.json"
        }
        assert listed == on_disk, f"{module} manifest mismatch"
