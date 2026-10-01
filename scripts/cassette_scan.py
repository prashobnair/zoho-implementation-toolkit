"""Fail on unredacted PII in recorded cassettes (STD-X2).

Scans ``cassettes/**`` and ``tests/contract/cassettes/**`` for:
- email addresses outside the ``example.invalid`` placeholder domain,
- phone-like digit runs (real numbers; masked ``+cc*****dd`` forms pass),
- configured org IDs listed in ``cassettes/known_org_ids.txt`` (one per
  line; absent file means no org-ID check).

Exit 0 when clean, exit 1 listing every offending file and line.

``555``-prefixed digit runs are treated as synthetic fixtures (the same
convention as ``example.invalid`` for mailboxes) and never flagged; real
org IDs are caught by the configured-ID check instead.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCAN_GLOBS = ("cassettes/**/*.json", "cassettes/**/*.yaml", "cassettes/**/*.yml")

#: Test/contract fixtures live beside the suite, not under cassettes/.
EXTRA_GLOBS = (
    "tests/contract/cassettes/**/*.json",
    "tests/contract/cassettes/**/*.yaml",
    "tests/contract/cassettes/**/*.yml",
)

ORG_IDS_FILE = ROOT / "cassettes" / "known_org_ids.txt"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_PHONE_RE = re.compile(r"\+?\d[\d\s\-().]{6,}\d")
_PLACEHOLDER_DOMAIN = "example.invalid"


def load_org_ids(path: Path = ORG_IDS_FILE) -> list[str]:
    """Configured org IDs, one per line; empty when the file is absent."""
    if not path.exists():
        return []
    ids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            ids.append(stripped)
    return ids


def scan_text(text: str, org_ids: list[str]) -> list[str]:
    """Return human-readable findings for one cassette body."""
    findings: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in _EMAIL_RE.finditer(line):
            if match.group(1).casefold() != _PLACEHOLDER_DOMAIN:
                findings.append(f"line {lineno}: unredacted email {match.group(0)!r}")
        for match in _PHONE_RE.finditer(line):
            digits = re.sub(r"\D", "", match.group(0))
            if digits.startswith("555"):
                continue
            findings.append(f"line {lineno}: unredacted phone {match.group(0)!r}")
        for org_id in org_ids:
            if org_id and org_id in line:
                findings.append(f"line {lineno}: configured org ID {org_id!r}")
    return findings


def iter_cassette_files(root: Path = ROOT) -> list[Path]:
    """Every cassette file under the scanned trees, sorted for stable output."""
    found: list[Path] = []
    for pattern in (*SCAN_GLOBS, *EXTRA_GLOBS):
        found.extend(sorted(root.glob(pattern)))
    return sorted(set(found))


def scan_all(root: Path = ROOT) -> dict[str, list[str]]:
    """Map offending relative paths to their findings (empty when clean)."""
    org_ids = load_org_ids(root / "cassettes" / "known_org_ids.txt")
    offenders: dict[str, list[str]] = {}
    for path in iter_cassette_files(root):
        findings = scan_text(path.read_text(encoding="utf-8", errors="replace"), org_ids)
        if findings:
            offenders[str(path.relative_to(root)).replace("\\", "/")] = findings
    return offenders


def main() -> int:
    """Entry point for the ``cassette-scan`` CI job."""
    offenders = scan_all()
    if not offenders:
        print(f"cassette-scan clean ({len(iter_cassette_files())} files)")
        return 0
    for path, findings in offenders.items():
        for finding in findings:
            print(f"{path}: {finding}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
