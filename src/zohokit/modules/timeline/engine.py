"""Timeline composer engine (TK-MIG-3).

Port of ``legacy/zoho-client-timeline-composer/timeline.py`` with one
intentional fix (TK-FIX-6): claim keys are normalized (casefold, strip,
``-``/space → ``_``); typed claims (``date``, ``number``, ``money``,
``text``) are normalized before comparison; untyped claims keep exact
string comparison. Timestamps go through core ``time.parse``.
"""

from __future__ import annotations

import copy
import hashlib
import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from zohokit.core.context import RunContext
from zohokit.core.findings import Finding, Report, Severity
from zohokit.core.ids import canonical_json
from zohokit.core.time import InvalidTimeError
from zohokit.core.time import parse as parse_time_core
from zohokit.modules import Analysis
from zohokit.modules.timeline.models import TimelineInput
from zohokit.modules.timeline.report import build_report

TYPES = {"call", "email_reference", "deal", "milestone"}
CLAIM_TYPES = {"date", "number", "money", "text"}


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be ISO-8601 string with timezone")
    try:
        return parse_time_core(value)
    except InvalidTimeError as exc:
        raise ValueError(str(exc)) from exc


def normalize_claim_key(key: str) -> str:
    """Normalize a claim key: casefold, strip, ``-``/space → ``_`` (TK-FIX-6)."""
    return re.sub(r"[- ]+", "_", key.strip().casefold())


def normalize_claim_value(value: str, claim_type: str | None) -> str:
    """Normalize a claim value for comparison (TK-FIX-6)."""
    text = value.strip()
    if claim_type == "date":
        try:
            return parse_time_core(text).date().isoformat()
        except InvalidTimeError:
            pass
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            return text.casefold()
    if claim_type == "number":
        try:
            normalized = format(Decimal(text.replace(",", "")), "f")
            if "." in normalized:
                normalized = normalized.rstrip("0").rstrip(".")
            return normalized
        except InvalidOperation:
            return text.casefold()
    if claim_type == "money":
        return re.sub(r"\s+", " ", text.replace(",", "").casefold()).strip()
    if claim_type == "text":
        return re.sub(r"\s+", " ", text.casefold()).strip()
    return value


def analyze(inputs: TimelineInput, *, audience: str = "internal") -> Analysis:
    """Compose the timeline; return findings plus the legacy dict."""
    events = copy.deepcopy(inputs.events)
    if not isinstance(events, list) or audience not in {"internal", "client"}:
        raise ValueError("events must be list and audience internal/client")
    ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    claims: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in events:
        if not isinstance(row, dict):
            raise ValueError("event must be object")
        eid = str(row.get("id", "")).strip()
        if not eid or eid in ids:
            raise ValueError("event IDs must be unique and nonempty")
        ids.add(eid)
        kind = row.get("type")
        if kind not in TYPES:
            raise ValueError("unsupported event type")
        if not isinstance(row.get("source_id"), str) or not row["source_id"]:
            raise ValueError("each event needs source_id")
        if row.get("visibility") not in {"internal", "client"}:
            raise ValueError("visibility must be internal/client")
        if not isinstance(row.get("summary"), str):
            raise ValueError("summary must be text")
        when = _parse_time(row.get("at"))
        entry = {
            "id": eid,
            "type": kind,
            "at": when.isoformat(),
            "summary": row["summary"],
            "source_id": row["source_id"],
            "visibility": row["visibility"],
        }
        if audience == "internal" or row["visibility"] == "client":
            normalized.append(entry)
            claim = row.get("claim")
            if isinstance(claim, dict) and isinstance(claim.get("key"), str):
                claim_type = claim.get("type") if claim.get("type") in CLAIM_TYPES else None
                claims[normalize_claim_key(claim["key"])].append(
                    (eid, normalize_claim_value(str(claim.get("value", "")), claim_type))
                )
    for key, values in sorted(claims.items()):
        if len({compared for _, compared in values}) > 1:
            conflicts.append(
                {"key": key, "event_ids": [eid for eid, _ in values], "code": "conflicting_claims"}
            )
    normalized.sort(key=lambda item: (item["at"], item["id"]))
    ready = not conflicts
    legacy = {
        "audience": audience,
        "timeline": normalized,
        "conflicts": conflicts,
        "source_count": len(events),
        "visible_count": len(normalized),
    }
    created = tuple(
        Finding.create(
            module="timeline",
            code="conflicting_claims",
            severity=Severity.ERROR,
            entity="timeline",
            entity_id=conflict["key"],
            message=f"Conflicting claims for {conflict['key']!r}: "
            + ", ".join(conflict["event_ids"]),
            evidence={"legacy_conflict": conflict},
            discriminator=conflict["key"],
        )
        for conflict in conflicts
    )
    return Analysis(findings=created, legacy=legacy, ready=ready)


def run(inputs: TimelineInput, *, ctx: RunContext, audience: str = "internal") -> Report:
    """Compose the timeline: ``run(inputs, *, ctx) -> Report`` (TK-ARCH-1)."""
    analysis = analyze(inputs, audience=audience)
    digest = hashlib.sha256(
        canonical_json({**inputs.model_dump(mode="json"), "audience": audience}).encode("utf-8")
    ).hexdigest()
    return build_report(analysis, ctx=ctx, inputs_sha256=digest)


__all__: list[str] = ["analyze", "normalize_claim_key", "normalize_claim_value", "run"]
