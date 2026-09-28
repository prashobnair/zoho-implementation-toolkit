"""Run fenced ``sh`` blocks tagged ``<!-- ci:run -->`` (STD-D3).

Scans ``README.md``: every ``<!-- ci:run -->`` marker applies to the next
fenced ``sh`` block. Each non-empty, non-comment line runs sequentially in
the repo root; the first nonzero exit fails the run. Only offline commands
belong in tagged blocks.

Usage: ``uv run python scripts/run_tagged_commands.py`` (repo root).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def tagged_blocks(text: str) -> list[list[str]]:
    """Return the command lines of each tagged ``sh`` fence."""
    blocks: list[list[str]] = []
    armed = False
    in_fence = False
    current: list[str] = []
    for line in text.splitlines():
        if "<!-- ci:run -->" in line:
            armed = True
            continue
        if line.strip() == "```sh" and armed and not in_fence:
            in_fence = True
            current = []
            continue
        if line.strip() == "```" and in_fence:
            in_fence = False
            armed = False
            blocks.append(current)
            continue
        if in_fence and line.strip() and not line.strip().startswith("#"):
            current.append(line.strip())
    return blocks


def main() -> int:
    blocks = tagged_blocks((ROOT / "README.md").read_text(encoding="utf-8"))
    if not blocks:
        print("no tagged blocks found", file=sys.stderr)
        return 1
    for block in blocks:
        for command in block:
            print(f"+ {command}")
            completed = subprocess.run(command, shell=True, cwd=ROOT, check=False)
            if completed.returncode != 0:
                print(f"FAILED ({completed.returncode}): {command}", file=sys.stderr)
                return 1
    print(f"ran {sum(len(block) for block in blocks)} tagged commands OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
