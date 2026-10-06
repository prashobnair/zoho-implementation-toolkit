"""Marigold generator determinism: reruns are byte-identical."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
MARIGOLD = ROOT / "fixtures" / "migration" / "marigold"


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_generator_rerun_is_byte_identical(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    script = ROOT / "scripts" / "gen_marigold_migration.py"
    for target in (first, second):
        proc = subprocess.run(
            [sys.executable, str(script), "--out", str(target)],
            capture_output=True,
            text=True,
            check=False,
            cwd=ROOT,
        )
        assert proc.returncode == 0, proc.stderr
    assert _snapshot(first) == _snapshot(second)
    assert _snapshot(first) == _snapshot(MARIGOLD)
