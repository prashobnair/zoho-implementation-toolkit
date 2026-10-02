"""Scope hygiene: read-only scopes only (STD-L2, TK-CONN-1)."""

from __future__ import annotations

OVER_PRIVILEGED_MARKERS = ("ALL", "CREATE", "UPDATE", "DELETE", "WRITE")

#: Read scopes the toolkit asks for per product area.
READ_SCOPES = {
    "crm": [
        "ZohoCRM.modules.READ",
        "ZohoCRM.settings.READ",
        "ZohoCRM.users.READ",
        "ZohoCRM.org.READ",
    ],
    "books": ["ZohoBooks.settings.READ"],
}


def find_over_privileged(scopes: list[str]) -> list[str]:
    """Return configured scopes that grant more than read access."""
    offenders: list[str] = []
    for scope in scopes:
        head = scope.split(".")[-1].upper()
        if head in OVER_PRIVILEGED_MARKERS or ".ALL" in scope.upper():
            offenders.append(scope)
    return offenders


def sufficient_for(scopes: list[str], needed: list[str]) -> list[str]:
    """Return the subset of *needed* scopes not covered by *scopes*."""
    have = set(scopes)
    return [scope for scope in needed if scope not in have]


__all__: list[str] = [
    "OVER_PRIVILEGED_MARKERS",
    "READ_SCOPES",
    "find_over_privileged",
    "sufficient_for",
]
