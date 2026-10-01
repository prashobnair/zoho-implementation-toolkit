"""Re-run the shared redactor over recorded cassettes (``make scrub``)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from scripts.cassette_scan import iter_cassette_files  # noqa: E402
from zohokit.core.redact import Redactor  # noqa: E402


def main() -> int:
    """Redact every cassette file in place; prints what changed."""
    redactor = Redactor()
    changed = 0
    for path in iter_cassette_files():
        if path.suffix != ".json":
            continue
        original = path.read_text(encoding="utf-8")
        try:
            payload = json.loads(original)
        except ValueError:
            continue
        scrubbed = json.dumps(redactor.redact_obj(payload), indent=2, sort_keys=True) + "\n"
        if scrubbed != original:
            path.write_text(scrubbed, encoding="utf-8")
            changed += 1
            print(f"scrubbed {path.relative_to(ROOT)}")
    print(f"scrub done ({changed} file(s) rewritten)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
