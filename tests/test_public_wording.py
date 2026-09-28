"""Public-wording guard: tracked files stay free of internal planning labels.

Public docs, help text and comments must use product language (releases
and versions such as v0.2.0), never internal tracking labels. The
changelog keeps its history and is exempt. The pattern below is built
from fragments so this file itself passes the same rule.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_BANNED = re.compile(
    r"\b"
    + "W"
    + r"P-?\d+\b"
    + r"|"
    + "work"
    + " package"
    + r"|"
    + "program"
    + " lead"
    + r"|"
    + "Inst"
    + "inct"
    + r"|"
    + "Open"
    + "Code",
    re.IGNORECASE,
)

_EXEMPT = {"CHANGELOG.md"}


def _tracked_names() -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [name for name in proc.stdout.split("\0") if name]


def test_no_internal_labels_in_tracked_files() -> None:
    hits: list[str] = []
    for name in _tracked_names():
        if Path(name).name in _EXEMPT:
            continue
        text = (ROOT / name).read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _BANNED.search(line):
                hits.append(f"{name}:{lineno}:{line.strip()[:120]}")
    assert not hits, "internal labels leaked into public files:\n" + "\n".join(hits[:20])
