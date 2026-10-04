"""UTF-8 regression: piped ``release diff`` must survive a cp1252 pipe.

On Windows the console/pipe encoding is cp1252 when ``PYTHONIOENCODING``
is unset, and the release v2 attribute diffs intentionally contain
``→`` (U+2192). Without ``ensure_utf8_stdio`` the CLI crashes with
``UnicodeEncodeError`` (exit 1) whenever stdout is redirected or piped.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BEFORE = ROOT / "fixtures" / "release" / "before.json"
AFTER = ROOT / "fixtures" / "release" / "after.json"


def _run_cli(extra: list[str]) -> subprocess.CompletedProcess[bytes]:
    """Run the CLI with no ``PYTHONIOENCODING`` and ``PYTHONUTF8=0`` piped."""
    env = dict(os.environ)
    env.pop("PYTHONIOENCODING", None)
    env["PYTHONUTF8"] = "0"
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from zohokit.cli import main; main()",
            "release",
            "diff",
            "--before",
            str(BEFORE),
            "--after",
            str(AFTER),
            "--format",
            "json",
            *extra,
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        env=env,
        timeout=120,
    )


def test_release_diff_piped_stdout_keeps_arrow() -> None:
    proc = _run_cli([])
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[:2000]
    assert "→" in proc.stdout.decode("utf-8")


def test_release_diff_piped_stdout_strict_exit_2_keeps_arrow() -> None:
    proc = _run_cli(["--strict"])
    assert proc.returncode == 2, proc.stderr.decode("utf-8", "replace")[:2000]
    assert "→" in proc.stdout.decode("utf-8")
