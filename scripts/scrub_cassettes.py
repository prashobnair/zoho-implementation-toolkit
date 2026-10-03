"""Re-run the shared redactor over recorded cassettes (``make scrub``).

With no arguments every ``*.json`` cassette under the scanned trees is
redacted in place. Pass explicit directories to redact those trees
instead (the weekly live job runs
``python scripts/scrub_cassettes.py cassettes evidence`` over the redacted
evidence bundle before the scan)::

    python scripts/scrub_cassettes.py [DIR ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.cassette_scan import iter_cassette_files  # noqa: E402
from zohokit.core.redact import Redactor  # noqa: E402


def scrub_file(path: Path, redactor: Redactor) -> bool:
    """Redact one JSON file in place; True when it changed."""
    original = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(original)
    except ValueError:
        return False
    scrubbed = json.dumps(redactor.redact_obj(payload), indent=2, sort_keys=True) + "\n"
    if scrubbed != original:
        path.write_text(scrubbed, encoding="utf-8")
        try:
            shown = str(path.relative_to(ROOT))
        except ValueError:
            shown = str(path)
        print(f"scrubbed {shown}")
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    """Redact every JSON file in place; prints what changed.

    No arguments scrubs the default cassette trees; explicit directories
    scrub those trees instead. ``argv`` must be passed explicitly: a bare
    call never reads ``sys.argv``.
    """
    args = list(argv) if argv is not None else []
    if args:
        targets = [
            path
            for arg in args
            for path in (
                [Path(arg)]
                if Path(arg).is_file()
                else sorted(p for p in Path(arg).rglob("*.json") if p.is_file())
            )
        ]
    else:
        targets = [path for path in iter_cassette_files() if path.suffix == ".json"]
    redactor = Redactor()
    changed = sum(1 for path in targets if scrub_file(path, redactor))
    print(f"scrub done ({changed} file(s) rewritten)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
