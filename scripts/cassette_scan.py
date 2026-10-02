"""Fail on unredacted PII or credentials in recorded cassettes (STD-X2).

Scans ``cassettes/**`` and ``tests/contract/cassettes/**`` for:
- email addresses outside the ``example.invalid`` placeholder domain,
- phone-like digit runs (real numbers; masked ``+cc*****dd`` forms pass),
- configured org IDs listed in ``cassettes/known_org_ids.txt`` (one per
  line; absent file means no org-ID check),
- OAuth credential patterns (``Zoho-oauthtoken <tok>``, ``Bearer <tok>``,
  Zoho ``1000.<hex>.<hex>`` tokens) and credential keys
  (``access_token``/``refresh_token``/``client_secret``/``client_id``/
  ``id_token``/``authorization``/``cookie``/``set-cookie``/``x-api-key``)
  whose value is not ``[redacted-credential]``.

Exit 0 when clean, exit 1 listing every offending file and line.

Findings are always value-free: each line reports the file, the line
number, the JSON key (the ``"key":`` on that line when the line parses
as a JSON member, else ``unknown``) and the category (``email``,
``phone``, ``credential`` or ``org_id``). Matched values are NEVER
echoed, so the scan gate itself can never leak PII into a public log.

``555``-prefixed digit runs are treated as synthetic fixtures (the same
convention as ``example.invalid`` for mailboxes) and never flagged; real
org IDs are caught by the configured-ID check instead. Opaque
``sha256:<hex>`` fingerprints are safe to share by design and never
flagged, so redacted live evidence passes the same scan.

Pass explicit directories to scan those trees instead (the nightly live
job runs ``python scripts/cassette_scan.py evidence cassettes`` over the
redacted evidence bundle before upload)::

    python scripts/cassette_scan.py [DIR ...]
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
_FINGERPRINT_RE = re.compile(r"sha256:[0-9a-fA-F]{8,}")
_PLACEHOLDER_DOMAIN = "example.invalid"

_ZOHO_OAUTHTOKEN_RE = re.compile(r"Zoho-oauthtoken\s+([^\s,;\"']+)", re.IGNORECASE)
_BEARER_RE = re.compile(r"Bearer\s+([A-Za-z0-9\-._~+/=]+)", re.IGNORECASE)
_ZOHO_TOKEN_RE = re.compile(r"\b1000\.[0-9a-fA-F]{2,}\.[0-9a-fA-F]{2,}\b")

_REDACTED_CREDENTIAL = "[redacted-credential]"

_CREDENTIAL_KEYS = (
    "access_token",
    "refresh_token",
    "client_secret",
    "client_id",
    "id_token",
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
)
_CREDENTIAL_KEY_RE = re.compile(
    r"(?i)[\"']?(" + "|".join(re.escape(key) for key in _CREDENTIAL_KEYS) + r")[\"']?\s*[:=]"
)


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


#: A JSON member on one pretty-printed line: ``"some_key": ...``.
_KEY_OF_LINE_RE = re.compile(r'"([^"]+)"\s*:')


def key_of_line(line: str) -> str:
    """JSON key for a scanned line (``unknown`` when it has no ``"key":``).

    Never returns a value: only the member name left of the colon, so the
    finding that carries it stays value-free.
    """
    match = _KEY_OF_LINE_RE.search(line)
    return match.group(1) if match is not None else "unknown"


def scan_text(text: str, org_ids: list[str]) -> list[str]:
    """Return value-free findings for one cassette body.

    Each finding names the line number, the JSON key on that line (when
    the line parses as a JSON member) and the category only — matched
    values are never included, so findings are safe for public logs.
    """
    # Fingerprints are opaque by design: drop them before the digit-run
    # scan so a hash holding 8+ consecutive digits never reads as a phone.
    text = _FINGERPRINT_RE.sub("sha256:", text)
    findings: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        key = key_of_line(line)
        for match in _EMAIL_RE.finditer(line):
            if match.group(1).casefold() != _PLACEHOLDER_DOMAIN:
                findings.append(f"line {lineno}: unredacted email [key: {key}]")
        for match in _PHONE_RE.finditer(line):
            digits = re.sub(r"\D", "", match.group(0))
            if digits.startswith("555"):
                continue
            findings.append(f"line {lineno}: unredacted phone [key: {key}]")
        for match in _ZOHO_OAUTHTOKEN_RE.finditer(line):
            if _REDACTED_CREDENTIAL not in match.group(1):
                findings.append(f"line {lineno}: unredacted credential [key: {key}]")
        for match in _BEARER_RE.finditer(line):
            if _REDACTED_CREDENTIAL not in match.group(1):
                findings.append(f"line {lineno}: unredacted credential [key: {key}]")
        if _ZOHO_TOKEN_RE.search(line):
            findings.append(f"line {lineno}: unredacted credential [key: {key}]")
        key_match = _CREDENTIAL_KEY_RE.search(line)
        if key_match is not None and _REDACTED_CREDENTIAL not in line:
            findings.append(f"line {lineno}: unredacted credential [key: {key_match.group(1)}]")
        for org_id in org_ids:
            if org_id and org_id in line:
                findings.append(f"line {lineno}: configured org ID [key: {key}]")
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


#: File types scanned inside explicitly passed directories.
EXTRA_SUFFIXES = (".json", ".yaml", ".yml", ".md")


def scan_paths(paths: list[Path], root: Path = ROOT) -> dict[str, list[str]]:
    """Scan every supported file under *paths* (files or directories)."""
    org_ids = load_org_ids(root / "cassettes" / "known_org_ids.txt")
    offenders: dict[str, list[str]] = {}
    for path in paths:
        candidates = (
            [path]
            if path.is_file()
            else sorted(p for p in path.rglob("*") if p.is_file() and p.suffix in EXTRA_SUFFIXES)
        )
        for candidate in candidates:
            try:
                rel = str(candidate.relative_to(root)).replace("\\", "/")
            except ValueError:
                rel = str(candidate)
            findings = scan_text(candidate.read_text(encoding="utf-8", errors="replace"), org_ids)
            if findings:
                offenders[rel] = findings
    return offenders


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``cassette-scan`` CI job.

    No arguments scans the default cassette trees; explicit directories
    scan those trees instead. ``argv`` must be passed explicitly (unlike
    ``argparse``, a bare call never reads ``sys.argv``).
    """
    args = list(argv) if argv is not None else []
    if args:
        offenders = scan_paths([Path(arg) for arg in args])
        if not offenders:
            print(f"cassette-scan clean ({len(args)} explicit path(s))")
            return 0
    else:
        offenders = scan_all()
        if not offenders:
            print(f"cassette-scan clean ({len(iter_cassette_files())} files)")
            return 0
    for path, findings in offenders.items():
        for finding in findings:
            print(f"{path}: {finding}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
