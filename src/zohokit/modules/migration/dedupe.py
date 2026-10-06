"""In-source duplicate clusters (TK-MIG-F4).

Rows sharing a normalized email, an E.164 phone, or a fuzzy company
name (rapidfuzz token-set ratio at or above threshold) form a cluster.
Each cluster yields one ``fuzzy_duplicate_cluster`` finding carrying a
*suggested* survivor; nothing is ever merged.

Determinism (KI-001): clusters key rows by content (source ID or row
hash, never input position), the survivor is the earliest created time
then the lexicographically smallest source ID, and finding IDs hash the
sorted member keys. Shuffling the input changes no finding ID and no
survivor (property-tested).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date as date_cls

from rapidfuzz import fuzz

from zohokit.core import emails as emails_core
from zohokit.core import phones as phones_core
from zohokit.core.findings import Finding, Severity
from zohokit.core.ids import canonical_json

#: Fuzzy company threshold: token-set ratio at or above this clusters.
COMPANY_THRESHOLD = 85

#: Created-column candidates, first present wins.
CREATED_COLS = ("Created", "Create Date", "created", "created_time", "Created Time")

#: Source-ID column candidates, first present wins.
ID_COLS = ("ID", "Contact ID", "Deal ID", "Company ID", "id")

#: Header fallbacks when the mapping names no signal column.
FALLBACK_EMAIL_COLS = ("Email", "email")
FALLBACK_PHONE_COLS = ("Phone", "phone", "Phone Number")
#: Header fallbacks when the mapping names no signal column. ``Name`` is
#: deliberately absent: bare names collide across unrelated rows, so
#: company matching needs a mapped company column or an explicit header.
FALLBACK_COMPANY_COLS = ("Company", "Company Name", "Organization")

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M")


@dataclass(frozen=True)
class RowSignals:
    """Content-derived identity plus match signals for one row."""

    key: str
    email: str | None
    phone: str | None
    company: str
    created: str


@dataclass
class Cluster:
    """One duplicate cluster: sorted member keys plus the survivor."""

    members: tuple[str, ...]
    survivor: str
    signals: tuple[str, ...] = ()


def normalize_email_cell(value: str | None) -> str | None:
    """Normalized email or None when missing/invalid (never raises)."""
    if value is None or value.strip() == "":
        return None
    try:
        return emails_core.normalize(value)
    except emails_core.EmailError:
        return None


def normalize_phone_cell(value: str | None, *, default_region: str | None) -> str | None:
    """E.164 phone or None when missing/unparseable (never raises)."""
    if value is None or value.strip() == "":
        return None
    try:
        return phones_core.parse(value, default_region=default_region).e164
    except phones_core.PhoneError:
        return None


def parse_created_cell(value: str | None) -> str:
    """ISO date for ordering, or ``""`` when missing/unparseable (sorts last)."""
    if value is None or value.strip() == "":
        return ""
    text = value.strip()
    try:
        return date_cls.fromisoformat(text[:10]).isoformat()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            from datetime import datetime as datetime_cls

            return datetime_cls.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def row_key(row: dict[str, str], id_col: str | None) -> str:
    """Content key: source ID when present, else a row-content hash."""
    if id_col is not None:
        candidate = (row.get(id_col) or "").strip()
        if candidate:
            return candidate
    digest = hashlib.sha256(canonical_json(row).encode("utf-8")).hexdigest()[:12]
    return f"hash:{digest}"


def pick_columns(
    header: list[str],
    mapped: dict[str, list[str]],
    fallbacks: tuple[str, ...],
) -> list[str]:
    """Mapping-named columns first, else the first fallback present."""
    wanted = [col for cols in mapped.values() for col in cols if col in header]
    if wanted:
        return wanted
    return [col for col in fallbacks if col in header][:1]


def signal_row(
    row: dict[str, str],
    *,
    id_col: str | None,
    email_cols: list[str],
    phone_cols: list[str],
    company_cols: list[str],
    created_cols: list[str],
    default_region: str | None,
) -> RowSignals:
    """Derive one row's signals (pure; order-independent)."""
    email: str | None = None
    for col in email_cols:
        email = normalize_email_cell(row.get(col))
        if email is not None:
            break
    phone: str | None = None
    for col in phone_cols:
        phone = normalize_phone_cell(row.get(col), default_region=default_region)
        if phone is not None:
            break
    company = ""
    for col in company_cols:
        candidate = (row.get(col) or "").strip()
        if candidate:
            company = candidate
            break
    created = ""
    for col in created_cols:
        created = parse_created_cell(row.get(col))
        if created:
            break
    return RowSignals(
        key=row_key(row, id_col),
        email=email,
        phone=phone,
        company=company,
        created=created,
    )


def cluster_signals(
    signals: list[RowSignals], *, company_threshold: int = COMPANY_THRESHOLD
) -> list[Cluster]:
    """Union rows sharing email/phone/fuzzy-company; pick survivors.

    Pure over the signal list: identical multisets cluster identically no
    matter the input order (ties break by content, never by position).
    """
    parent = list(range(len(signals)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        root_i, root_j = find(i), find(j)
        if root_i != root_j:
            parent[root_j] = root_i

    by_email: dict[str, int] = {}
    by_phone: dict[str, int] = {}
    for index, sig in enumerate(signals):
        if sig.email is not None:
            if sig.email in by_email:
                union(index, by_email[sig.email])
            else:
                by_email[sig.email] = index
        if sig.phone is not None:
            if sig.phone in by_phone:
                union(index, by_phone[sig.phone])
            else:
                by_phone[sig.phone] = index
    with_company = [index for index, sig in enumerate(signals) if sig.company]
    for left_pos in range(len(with_company)):
        for right_pos in range(left_pos + 1, len(with_company)):
            left, right = with_company[left_pos], with_company[right_pos]
            if find(left) == find(right):
                continue
            left_name = signals[left].company
            right_name = signals[right].company
            if fuzz.token_set_ratio(left_name, right_name) >= company_threshold:
                union(left, right)
    groups: dict[int, list[int]] = {}
    for index in range(len(signals)):
        groups.setdefault(find(index), []).append(index)
    clusters: list[Cluster] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        member_sigs = [signals[i] for i in members]
        keys = sorted(sig.key for sig in member_sigs)
        fired: set[str] = set()
        emails = [sig.email for sig in member_sigs if sig.email]
        phones = [sig.phone for sig in member_sigs if sig.phone]
        if len(set(emails)) < len(emails):
            fired.add("email")
        if len(set(phones)) < len(phones):
            fired.add("phone")
        if "email" not in fired and "phone" not in fired:
            fired.add("company")
        # Earliest created time, then smallest source ID: content only.
        survivor = min(member_sigs, key=lambda sig: (sig.created or "\uffff", sig.key)).key
        clusters.append(
            Cluster(members=tuple(keys), survivor=survivor, signals=tuple(sorted(fired)))
        )
    clusters.sort(key=lambda cluster: cluster.members)
    return clusters


def cluster_findings(entity_name: str, clusters: list[Cluster]) -> list[Finding]:
    """One review finding per cluster, placed on the survivor (suggested).

    The discriminator hashes the sorted member keys, so IDs survive any
    input reordering. The cluster is never merged: the survivor is a
    suggestion with its rationale in evidence.
    """
    findings: list[Finding] = []
    for cluster in clusters:
        digest = hashlib.sha256(canonical_json(list(cluster.members)).encode()).hexdigest()[:16]
        findings.append(
            Finding.create(
                module="migration",
                code="fuzzy_duplicate_cluster",
                severity=Severity.REVIEW,
                entity=entity_name,
                entity_id=cluster.survivor,
                message="Rows may duplicate each other; review before import (never auto-merged).",
                evidence={
                    "survivor": cluster.survivor,
                    "members": list(cluster.members),
                    "signals": list(cluster.signals),
                },
                remediation="Keep the suggested survivor or pick another; remove the rest.",
                discriminator=f"cluster\0{digest}",
            )
        )
    return findings


__all__: list[str] = [
    "COMPANY_THRESHOLD",
    "CREATED_COLS",
    "FALLBACK_COMPANY_COLS",
    "FALLBACK_EMAIL_COLS",
    "FALLBACK_PHONE_COLS",
    "ID_COLS",
    "Cluster",
    "RowSignals",
    "cluster_findings",
    "cluster_signals",
    "normalize_email_cell",
    "normalize_phone_cell",
    "parse_created_cell",
    "pick_columns",
    "row_key",
    "signal_row",
]
