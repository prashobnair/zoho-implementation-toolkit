"""Owner email mapping against Zoho users (TK-MIG-F7).

Source owner emails resolve through the verified ``/crm/v8/users``
endpoint (offline: a users file; live: the endpoint). Inactive users
yield ``inactive_owner``; unmapped emails yield ``owner_unmapped``.
Owner emails appear in findings redacted only (STD-X1).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from zohokit.core.findings import Finding, Severity
from zohokit.core.redact import mask_email
from zohokit.modules.migration.mapping import EntityMapping

#: Target fields treated as the owner carrier.
OWNER_TARGETS = ("Owner",)


def owner_column(entity: EntityMapping, header: list[str]) -> str | None:
    """Source column feeding the target Owner field, if mapped and present."""
    for target in OWNER_TARGETS:
        field_map = entity.fields.get(target)
        if field_map is not None and field_map.from_col in header:
            return field_map.from_col
    return None


def users_from_envelope(payload: Any) -> dict[str, str]:
    """Map normalized owner email -> account status from a users payload.

    Accepts the recorded envelope (``response.body.users``), the bare
    body (``{"users": [...]}``) and the bare list. Statuses casefold;
    anything but ``active`` counts as inactive.
    """
    node: Any = payload
    if isinstance(node, dict) and "response" in node:
        node = node["response"]
        if isinstance(node, dict) and "body" in node:
            node = node["body"]
    if isinstance(node, dict) and isinstance(node.get("users"), list):
        node = node["users"]
    if not isinstance(node, list):
        raise ValueError("users payload must carry a 'users' list")
    out: dict[str, str] = {}
    for entry in node:
        if not isinstance(entry, dict):
            continue
        email = entry.get("email")
        if isinstance(email, str) and email.strip():
            out[email.strip().casefold()] = str(entry.get("status", "") or "").casefold()
    return out


def users_from_file(path: str | Path) -> dict[str, str]:
    """Load owner statuses from a users JSON file (offline target)."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    try:
        return users_from_envelope(payload)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def check_owners(
    entity: EntityMapping,
    rows: list[tuple[str, dict[str, str]]],
    header: list[str],
    users: dict[str, str],
) -> list[Finding]:
    """Resolve each row's owner email; flag inactive and unmapped owners."""
    column = owner_column(entity, header)
    if column is None:
        return []
    findings: list[Finding] = []
    for key, row in rows:
        raw = (row.get(column) or "").strip()
        if not raw:
            continue
        status = users.get(raw.casefold())
        if status is None:
            findings.append(
                Finding.create(
                    module="migration",
                    code="owner_unmapped",
                    severity=Severity.ERROR,
                    entity=entity.name,
                    entity_id=key,
                    message="Owner email matches no user in the target org.",
                    evidence={"owner": mask_email(raw)},
                    remediation="Add the user to the target org or remap the owner.",
                    discriminator=f"owner\0{raw.casefold()}",
                )
            )
        elif status != "active":
            findings.append(
                Finding.create(
                    module="migration",
                    code="inactive_owner",
                    severity=Severity.ERROR,
                    entity=entity.name,
                    entity_id=key,
                    message="Owner email belongs to an inactive target user.",
                    evidence={"owner": mask_email(raw)},
                    remediation="Reactivate the user or remap the owner.",
                    discriminator=f"owner\0{raw.casefold()}",
                )
            )
    return findings


__all__: list[str] = [
    "OWNER_TARGETS",
    "check_owners",
    "owner_column",
    "users_from_envelope",
    "users_from_file",
]
