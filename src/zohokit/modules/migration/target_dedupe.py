"""Duplicate detection against existing target records (TK-MIG-F5).

For each source row (email first, then phone) the check searches the
target module through the record-search endpoint. That endpoint is
`unverified` (see ``docs/API_CONTRACTS.md``), so live searches run only
behind ``--experimental``; tests use synthetic cassettes shaped like the
real v8 envelope. Matching target IDs surface as fingerprints only.

Budget-aware: rows carrying an email are checked first; the search stops
at the budget and reports coverage (``checked N / M``) in an info
finding, truncated or not.
"""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256

from zohokit.core.findings import Finding, Severity

#: Search function: (target module, email | None, phone | None) -> target fingerprints.
SearchFn = Callable[[str, str | None, str | None], list[str]]


def target_fingerprint(record_id: str) -> str:
    """Opaque ``sha256:`` fingerprint of a target record ID (never the ID)."""
    return "sha256:" + sha256(record_id.encode("utf-8")).hexdigest()[:32]


def check_against_target(
    entity_name: str,
    target_module: str,
    candidates: list[tuple[str, int, str | None, str | None]],
    search: SearchFn,
    *,
    budget: int | None = None,
) -> tuple[list[Finding], int, int, bool]:
    """Search the target for each candidate; return findings + coverage.

    *candidates* are ``(row key, physical line, email | None, phone |
    None)`` with email carriers first (callers order them). The key is
    the stable source record key (never a position); the line lands in
    evidence only (never in the finding identity). At most *budget*
    searches run (None means unbounded). Returns ``(findings, checked,
    total, truncated)``; callers report coverage from the counts.
    """
    findings: list[Finding] = []
    checked = 0
    truncated = False
    for key, line, email, phone in candidates:
        if email is None and phone is None:
            continue
        if budget is not None and checked >= budget:
            truncated = True
            break
        matches = search(target_module, email, phone)
        checked += 1
        for fingerprint in sorted(set(matches)):
            matched_on = "email" if email is not None else "phone"
            findings.append(
                Finding.create(
                    module="migration",
                    code="would_duplicate_existing",
                    severity=Severity.REVIEW,
                    entity=entity_name,
                    entity_id=key,
                    message="Source row matches an existing target record; review before import.",
                    evidence={
                        "target_module": target_module,
                        "target_fingerprint": fingerprint,
                        "matched_on": matched_on,
                        "line": line,
                    },
                    remediation="Merge in the source, or plan an update instead of a create.",
                    discriminator=f"target\0{target_module}\0{key}",
                )
            )
    return findings, checked, len(candidates), truncated


def coverage_finding(entity_name: str, *, checked: int, total: int, truncated: bool) -> Finding:
    """Info finding reporting the target-search coverage (``checked N / M``)."""
    return Finding.create(
        module="migration",
        code="target_dedupe_coverage",
        severity=Severity.INFO,
        entity=entity_name,
        entity_id="coverage",
        message=f"Target duplicate search checked {checked} / {total} rows.",
        evidence={"checked": checked, "total": total, "truncated": truncated},
        remediation="Raise the API budget or narrow the batch when truncated.",
        discriminator=f"coverage\0{checked}\0{total}\0{int(truncated)}",
    )


__all__: list[str] = [
    "SearchFn",
    "check_against_target",
    "coverage_finding",
    "target_fingerprint",
]
