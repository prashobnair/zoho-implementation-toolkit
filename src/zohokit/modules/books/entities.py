"""Books entity map (TK-BK-F2): legal entities keyed locally, IDs in profiles.

The entity map is a YAML file ``{entity_key: {...}}``::

    in-entity:
      books_org_id_ref: in-entity      # key into the profile's books_orgs
      base_currency: INR
      crm_criteria: {field: Entity, equals: India}
    us-entity:
      books_org_id_ref: us-entity
      base_currency: USD
      crm_criteria: {field: Entity, equals: US}

Raw Books organization IDs live **only** in the local auth profile
(``books_orgs: {ref: organization_id}``) and never in the map, the
report, or the logs. Reports and evidence carry only the opaque
``sha256:<16-hex>`` fingerprint from :func:`org_fingerprint`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from zohokit.core.money import validate_currency


def org_fingerprint(organization_id: str) -> str:
    """Opaque ``sha256:<16-hex>`` fingerprint of a Books organization id."""
    return "sha256:" + hashlib.sha256(organization_id.encode("utf-8")).hexdigest()[:16]


class EntityEntry(BaseModel):
    """One legal entity: profile org-id reference, base currency, deal filter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    books_org_id_ref: str = Field(min_length=1)
    base_currency: str = "INR"
    crm_criteria: dict[str, Any] = Field(default_factory=dict)

    @property
    def currency(self) -> str:
        """Validated ISO 4217 base currency (upper-cased)."""
        return validate_currency(self.base_currency)


class EntityMapConfigError(ValueError):
    """An entity-map problem as ``path:line: detail`` (exit 1 at the CLI)."""

    def __init__(self, path: str | Path, line: int, detail: str) -> None:
        super().__init__(f"{path}:{line}: {detail}")
        self.path = str(path)
        self.line = line
        self.detail = detail


def load_entity_map(path: Path) -> dict[str, EntityEntry]:
    """Load and validate an entity-map YAML file (locations only in errors)."""
    text_path = Path(path)
    try:
        text = text_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise EntityMapConfigError(str(path), 1, f"cannot read entity map: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        line = getattr(getattr(exc, "problem_mark", None), "line", None)
        raise EntityMapConfigError(
            str(path), (line + 1) if isinstance(line, int) else 1, "invalid YAML"
        ) from exc
    if not isinstance(raw, dict) or not raw:
        raise EntityMapConfigError(str(path), 1, "entity map must be a non-empty YAML mapping")
    entries: dict[str, EntityEntry] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            raise EntityMapConfigError(str(path), 1, f"invalid entity map at {key}: not a mapping")
        try:
            entries[str(key)] = EntityEntry.model_validate(value)
        except ValidationError as exc:
            first = exc.errors(include_input=False, include_url=False)[0]
            loc = ".".join(str(step) for step in first.get("loc", ()))
            raise EntityMapConfigError(str(path), 1, f"invalid entity map at {key}.{loc}") from exc
    return entries


def resolve_org_ids(
    entities: dict[str, EntityEntry], profile_orgs: dict[str, str]
) -> dict[str, str]:
    """Resolve each entity's ``books_org_id_ref`` against the profile map.

    Raises :class:`EntityMapConfigError` naming the missing reference
    only (never any id value) when a ref has no profile entry.
    """
    resolved: dict[str, str] = {}
    for key, entry in entities.items():
        org_id = profile_orgs.get(entry.books_org_id_ref)
        if not org_id:
            raise EntityMapConfigError(
                "<profile>", 1, f"entity {key} references unknown books org ref"
            )
        resolved[key] = org_id
    return resolved


def deal_in_entity(deal: dict[str, Any], entry: EntityEntry) -> bool:
    """Whether *deal* belongs to *entry* under its ``crm_criteria``.

    The criteria form is ``{field: <name>, equals: <value>}``; an empty
    criteria matches every deal of the entity key. Unknown forms never
    match (fail closed).
    """
    criteria = entry.crm_criteria
    if not criteria:
        return True
    field = criteria.get("field")
    expected = criteria.get("equals")
    if not isinstance(field, str) or expected is None:
        return False
    return bool(deal.get(field) == expected)


__all__: list[str] = [
    "EntityEntry",
    "EntityMapConfigError",
    "deal_in_entity",
    "load_entity_map",
    "org_fingerprint",
    "resolve_org_ids",
]
