"""Migration preflight engine (TK-MIG-3).

Port of ``legacy/zoho-crm-migration-auditor/migration.py`` with one cleanup:
unused imports removed (TK-FIX-7). Logic and legacy output are unchanged.
"""

from __future__ import annotations

import copy
import hashlib
import re
from typing import Any

from zohokit.core.context import RunContext
from zohokit.core.findings import Finding, Report, Severity
from zohokit.core.ids import canonical_json
from zohokit.modules import Analysis
from zohokit.modules.migration.models import MigrationInput
from zohokit.modules.migration.report import build_report

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
ENTITIES = ("organizations", "people", "deals", "activities")

_SEVERITY = {"error": Severity.ERROR, "review": Severity.REVIEW}


def _row_id(row: dict[str, Any]) -> str:
    return str(row.get("id", "")).strip()


def analyze(inputs: MigrationInput) -> Analysis:
    """Audit the source export; return findings plus the legacy result dict."""
    payload = copy.deepcopy(inputs.model_dump())
    entities = ENTITIES
    if not isinstance(payload, dict) or any(not isinstance(payload.get(e), list) for e in entities):
        raise ValueError("Expected lists: organizations, people, deals, activities")
    mappings = payload.get("stage_mapping")
    if not isinstance(mappings, dict):
        raise ValueError("stage_mapping must be an object")
    issues: list[dict[str, Any]] = []
    ids: dict[str, set[str]] = {}
    for entity in entities:
        seen: set[str] = set()
        for row in payload[entity]:
            if not isinstance(row, dict):
                raise ValueError(f"{entity} must contain objects")
            key = _row_id(row)
            if not key:
                issues.append(
                    {
                        "severity": "error",
                        "entity": entity,
                        "source_id": "",
                        "code": "missing_id",
                        "detail": "Source ID is required",
                    }
                )
            elif key in seen:
                issues.append(
                    {
                        "severity": "error",
                        "entity": entity,
                        "source_id": key,
                        "code": "duplicate_id",
                        "detail": "Source ID repeats",
                    }
                )
            seen.add(key)
        ids[entity] = seen - {""}

    by_email: dict[str, str] = {}
    for person in payload["people"]:
        key, email = _row_id(person), str(person.get("email", "")).strip().casefold()
        if not EMAIL_RE.fullmatch(email):
            issues.append(
                {
                    "severity": "error",
                    "entity": "people",
                    "source_id": key,
                    "code": "invalid_email",
                    "detail": "Email cannot be matched safely",
                }
            )
        elif email in by_email:
            issues.append(
                {
                    "severity": "review",
                    "entity": "people",
                    "source_id": key,
                    "code": "possible_duplicate",
                    "detail": f"Email matches source person {by_email[email]}",
                }
            )
        else:
            by_email[email] = key
        if str(person.get("organization_id", "")) not in ids["organizations"]:
            issues.append(
                {
                    "severity": "error",
                    "entity": "people",
                    "source_id": key,
                    "code": "orphan_organization",
                    "detail": "Organization ID not present",
                }
            )

    for deal in payload["deals"]:
        key = _row_id(deal)
        if str(deal.get("person_id", "")) not in ids["people"]:
            issues.append(
                {
                    "severity": "error",
                    "entity": "deals",
                    "source_id": key,
                    "code": "orphan_person",
                    "detail": "Person ID not present",
                }
            )
        if str(deal.get("stage", "")) not in mappings:
            issues.append(
                {
                    "severity": "error",
                    "entity": "deals",
                    "source_id": key,
                    "code": "unmapped_stage",
                    "detail": "No approved target stage mapping",
                }
            )

    for activity in payload["activities"]:
        key = _row_id(activity)
        if str(activity.get("deal_id", "")) not in ids["deals"]:
            issues.append(
                {
                    "severity": "error",
                    "entity": "activities",
                    "source_id": key,
                    "code": "orphan_deal",
                    "detail": "Deal ID not present",
                }
            )

    order = {entity: index for index, entity in enumerate(entities)}
    issues.sort(key=lambda item: (order[item["entity"]], item["source_id"], item["code"]))
    counts = {entity: len(payload[entity]) for entity in entities}
    errors = sum(item["severity"] == "error" for item in issues)
    review = sum(item["severity"] == "review" for item in issues)
    ready = errors == 0 and review == 0
    # A duplicate is not silently merged. Even review-only imports need a human decision.
    legacy = {
        "mode": "dry_run_only",
        "ready_for_import": ready,
        "source_counts": counts,
        "target_preview_counts": counts if ready else None,
        "issues": issues,
        "import_order": list(entities),
        "rollback_manifest": {
            "precondition": "Keep original export and a dated target backup before any real import",
            "source_ids": {entity: sorted(ids[entity]) for entity in entities},
            "action": (
                "No rollback executed; validate target IDs "
                "and inverse dependencies in a pilot first"
            ),
        },
    }
    findings = tuple(
        Finding.create(
            module="migration",
            code=issue["code"],
            severity=_SEVERITY[issue["severity"]],
            entity=issue["entity"],
            entity_id=issue["source_id"],
            message=issue["detail"],
            evidence={"legacy_issue": issue},
            discriminator=f"{issue['entity']}\0{issue['source_id']}\0{issue['code']}",
        )
        for issue in issues
    )
    return Analysis(findings=findings, legacy=legacy, ready=ready)


def run(inputs: MigrationInput, *, ctx: RunContext) -> Report:
    """Run the audit: ``run(inputs, *, ctx) -> Report`` (TK-ARCH-1)."""
    analysis = analyze(inputs)
    digest = hashlib.sha256(
        canonical_json(inputs.model_dump(mode="json")).encode("utf-8")
    ).hexdigest()
    return build_report(analysis, ctx=ctx, inputs_sha256=digest)


__all__: list[str] = ["analyze", "run"]
