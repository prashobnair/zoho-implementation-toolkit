"""Target field metadata and mapping validation (TK-MIG-F3).

Metadata comes from the target org's *actual* field list: offline from
recorded ``fields_<Module>.json`` files (same envelope as
``cassettes/crm/fields_*.json``), or live from the verified
``/crm/v8/settings/fields`` endpoint (see ``live.py``). Every check maps
to a stable finding code; messages are value-free (field names and rule
parameters only, never cell values).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from zohokit.core.findings import Finding, Severity
from zohokit.modules.migration.mapping import (
    EntityMapping,
    MappingDoc,
    TransformError,
    apply_transforms,
)

#: Sample rows validated per entity (deterministic head sample).
SAMPLE_ROWS = 200

#: Zoho data types checked as ISO dates after transforms.
DATE_TYPES = frozenset({"date", "datetime"})

#: Zoho data types checked as Decimal amounts after transforms.
NUMBER_TYPES = frozenset({"double", "currency", "integer", "bigint", "number", "percent"})

#: Boolean spellings accepted (casefolded) for boolean/checkbox fields.
BOOLEAN_WORDS = frozenset({"true", "false", "1", "0", "yes", "no"})


class FieldMeta(BaseModel):
    """One target field: the subset of ``settings/fields`` the audit needs."""

    model_config = ConfigDict(frozen=True)

    api_name: str
    data_type: str = ""
    length: int | None = None
    pick_list_values: tuple[str, ...] = ()
    read_only: bool = False
    system_mandatory: bool = False
    unique: bool = False

    @classmethod
    def from_entry(cls, entry: dict[str, Any]) -> FieldMeta:
        """Coerce one ``settings/fields`` entry (cassette or live shape)."""
        raw_picks = entry.get("pick_list_values", [])
        picks: list[str] = []
        if isinstance(raw_picks, list):
            for item in raw_picks:
                if isinstance(item, dict) and isinstance(item.get("actual_value"), str):
                    picks.append(item["actual_value"])
                elif isinstance(item, str):
                    picks.append(item)
        length = entry.get("length")
        return cls(
            api_name=str(entry.get("api_name", "")),
            data_type=str(entry.get("data_type", "")),
            length=int(length) if isinstance(length, (int, float)) and length >= 0 else None,
            pick_list_values=tuple(picks),
            read_only=bool(entry.get("read_only", False)),
            system_mandatory=bool(entry.get("system_mandatory", False)),
            unique=bool(entry.get("unique", False)),
        )


class TargetMetadata(BaseModel):
    """Target modules mapped to their field lists (offline or live)."""

    model_config = ConfigDict(frozen=True)

    modules: dict[str, dict[str, FieldMeta]] = Field(default_factory=dict)

    def fields_for(self, module: str) -> dict[str, FieldMeta]:
        """Field map for *module* (empty when the module is unknown)."""
        return self.modules.get(module, {})


def _value_fingerprint(value: str) -> str:
    """Opaque ``sha256:`` fingerprint of a cell value (never the value)."""
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


#: Source-ID column fallbacks when the mapping declares no external ID
#: (mirrors ``dedupe.ID_COLS`` without importing it on this branch).
STABLE_ID_FALLBACK_COLS = ("ID", "Contact ID", "Deal ID", "Company ID", "id")


def _row_content_hash(row: dict[str, str]) -> str:
    """Content hash for rows with no usable ID column (never a position)."""
    from zohokit.core.ids import canonical_json

    digest = hashlib.sha256(canonical_json(row).encode("utf-8")).hexdigest()[:12]
    return f"hash:{digest}"


def stable_record_key(entity: EntityMapping, header: list[str], row: dict[str, str]) -> str:
    """Stable per-record key: external-ID value else a row-content hash.

    Uses the mapping's ``external_id.from`` column when it exists in the
    header and the row carries a non-empty value; otherwise the first
    ID-like fallback column present; otherwise a content hash of the row.
    Never a row index or file position, so prepending or shuffling rows
    changes no finding ID.

    The key is unique only when the source ID is: two batch rows sharing
    one ID share this key. Use :func:`disambiguated_record_keys` for the
    batch-aware keys that per-record findings actually carry.
    """
    if entity.external_id is not None and entity.external_id.from_col in header:
        candidate = (row.get(entity.external_id.from_col) or "").strip()
        if candidate:
            return candidate
    for col in STABLE_ID_FALLBACK_COLS:
        if col in header:
            candidate = (row.get(col) or "").strip()
            if candidate:
                return candidate
    return _row_content_hash(row)


def _row_content_suffix(row: dict[str, str]) -> str:
    """Short content hash of a row's normalized values (never the values)."""
    from zohokit.core.ids import canonical_json

    normalized = {
        key: (value.strip() if isinstance(value, str) else value) for key, value in row.items()
    }
    return hashlib.sha256(canonical_json(normalized).encode("utf-8")).hexdigest()[:8]


def disambiguated_record_keys(
    entity: EntityMapping,
    header: list[str],
    sample_rows: list[tuple[int, dict[str, str]]],
) -> list[str]:
    """Batch-aware record keys, aligned with *sample_rows*.

    A base key (:func:`stable_record_key`) that occurs more than once in
    the batch becomes ``<key>#<short content hash>`` so each colliding row
    carries a distinct key while every unique key is returned unchanged
    (existing finding IDs stay stable). The suffix hashes only the row's
    own normalized values, so reordering the batch or inserting other rows
    changes no key. Byte-identical rows share a key: by content they are
    the same record.
    """
    base = [stable_record_key(entity, header, row) for _, row in sample_rows]
    counts: dict[str, int] = {}
    for key in base:
        counts[key] = counts.get(key, 0) + 1
    return [
        f"{key}#{_row_content_suffix(row)}" if counts[key] > 1 else key
        for key, (_, row) in zip(base, sample_rows, strict=True)
    ]


def metadata_from_cassette_envelope(payload: Any) -> dict[str, FieldMeta]:
    """Read ``{"fields": [...]}`` from a cassette envelope or a bare payload.

    Accepts the recorded shape (``{"request": ..., "response": {"body":
    {"fields": [...]}}}``), the bare body (``{"fields": [...]}``) and the
    bare list itself. Anything else is a config error naming the shape.
    """
    node: Any = payload
    if isinstance(node, dict) and "response" in node:
        node = node["response"]
        if isinstance(node, dict) and "body" in node:
            node = node["body"]
    if isinstance(node, dict) and isinstance(node.get("fields"), list):
        node = node["fields"]
    if not isinstance(node, list):
        raise ValueError("field metadata must carry a 'fields' list")
    out: dict[str, FieldMeta] = {}
    for entry in node:
        if isinstance(entry, dict) and entry.get("api_name"):
            meta = FieldMeta.from_entry(entry)
            out[meta.api_name] = meta
    return out


def metadata_from_dir(directory: str | Path) -> TargetMetadata:
    """Load ``fields_<Module>.json`` files from *directory* (offline target).

    Files that are absent are simply unknown modules; malformed JSON is a
    config error naming the file.
    """
    modules: dict[str, dict[str, FieldMeta]] = {}
    base = Path(directory)
    if not base.is_dir():
        raise ValueError(f"metadata directory not found: {directory}")
    for path in sorted(base.glob("fields_*.json")):
        module = path.stem.removeprefix("fields_")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"cannot read {path}: {exc}") from exc
        try:
            modules[module] = metadata_from_cassette_envelope(payload)
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from exc
    return TargetMetadata(modules=modules)


def mapped_value(
    entity: EntityMapping, target: str, row: dict[str, str]
) -> tuple[str | None, TransformError | None]:
    """Apply the field's transforms to one row; capture transform failure."""
    field_map = entity.fields[target]
    if any(spec.name == "concat" for spec in field_map.transform):
        raw: str | None = None
    elif field_map.from_col is None:
        raw = None
    else:
        raw = row.get(field_map.from_col)
        if raw is not None and raw == "":
            raw = None
    try:
        return apply_transforms(raw, row, list(field_map.transform)), None
    except TransformError as exc:
        return None, exc


def _check_value(meta: FieldMeta, value: str) -> str | None:
    """Return the failure reason for *value* against *meta*, or None.

    Reasons are rule names only (``too_long``, ``not_in_picklist``,
    ``bad_syntax``); never cell values.
    """
    data_type = meta.data_type.casefold()
    if meta.length is not None and len(value) > meta.length:
        return "too_long"
    if data_type == "email":
        from zohokit.core import emails as emails_core

        try:
            emails_core.normalize(value)
        except emails_core.EmailError:
            return "bad_syntax"
    elif data_type == "date":
        from datetime import date as date_cls

        try:
            date_cls.fromisoformat(value.strip())
        except ValueError:
            return "bad_syntax"
    elif data_type == "datetime":
        from zohokit.core import time as time_core

        try:
            time_core.parse(value)
        except time_core.InvalidTimeError:
            return "bad_syntax"
    elif data_type in NUMBER_TYPES:
        from zohokit.core import money as money_core

        try:
            money_core.parse(value.strip(), allow_negative=True)
        except money_core.MoneyError:
            return "bad_syntax"
    elif data_type in ("boolean", "checkbox"):
        if value.strip().casefold() not in BOOLEAN_WORDS:
            return "bad_syntax"
    if data_type in ("picklist", "multiselectpicklist") and meta.pick_list_values:
        allowed = set(meta.pick_list_values)
        if data_type == "multiselectpicklist":
            candidates = [part.strip() for part in value.split(";")]
        else:
            candidates = [value]
        if any(item not in allowed for item in candidates):
            return "not_in_picklist"
    return None


def validate_entity(
    entity: EntityMapping,
    fields: dict[str, FieldMeta],
    header: list[str],
    sample_rows: list[tuple[int, dict[str, str]]],
) -> list[Finding]:
    """Validate one mapped entity against its target field list.

    Mapping-level problems (unknown/read-only target, mandatory gaps,
    unresolvable lookups) yield one finding per field; value problems
    (length, picklist, type) yield one finding per sampled row. Each
    per-record finding uses the batch-aware record key
    (:func:`disambiguated_record_keys`, never a row index) as ``entity_id``
    and carries the 1-based physical file line (header is line 1) in
    ``evidence["line"]`` so humans can find the row. Findings sort by the
    shared report order at build time.
    """
    findings: list[Finding] = []
    record_keys = disambiguated_record_keys(entity, header, sample_rows)
    for target, field_map in entity.fields.items():
        meta = fields.get(target)
        if meta is None:
            findings.append(
                Finding.create(
                    module="migration",
                    code="unknown_target_field",
                    severity=Severity.ERROR,
                    entity=entity.name,
                    entity_id=target,
                    message=f"Target field is not present in module {entity.target_module}.",
                    evidence={"target_module": entity.target_module, "target_field": target},
                    remediation="Fix the mapping or add the field to the target module first.",
                    discriminator=f"mapping\0{entity.target_module}\0{target}",
                )
            )
            continue
        if meta.read_only:
            findings.append(
                Finding.create(
                    module="migration",
                    code="read_only_target_field",
                    severity=Severity.ERROR,
                    entity=entity.name,
                    entity_id=target,
                    message=f"Target field is read-only in module {entity.target_module}.",
                    evidence={"target_module": entity.target_module, "target_field": target},
                    remediation="Remove the field from the mapping; the target fills it.",
                    discriminator=f"mapping\0{entity.target_module}\0{target}",
                )
            )
        if (
            field_map.from_col is not None
            and field_map.from_col not in header
            and not any(spec.name == "concat" for spec in field_map.transform)
        ):
            findings.append(
                Finding.create(
                    module="migration",
                    code="missing_source_column",
                    severity=Severity.ERROR,
                    entity=entity.name,
                    entity_id=target,
                    message="Source column is not present in the export header.",
                    evidence={"target_field": target, "source_column": field_map.from_col},
                    remediation="Fix the mapping 'from' column or re-export the source.",
                    discriminator=f"mapping\0{entity.target_module}\0{target}",
                )
            )
        for (line, row), record_key in zip(sample_rows, record_keys, strict=True):
            value, failed = mapped_value(entity, target, row)
            if failed is not None:
                findings.append(
                    Finding.create(
                        module="migration",
                        code="type_incompatible",
                        severity=Severity.ERROR,
                        entity=entity.name,
                        entity_id=record_key,
                        message="Value cannot be converted for target field (transform failed).",
                        evidence={
                            "target_field": target,
                            "transform": failed.transform,
                            "line": line,
                        },
                        remediation="Fix the source value or adjust the mapping transform.",
                        discriminator=f"value\0{entity.target_module}\0{target}\0{record_key}",
                    )
                )
                continue
            if value is None or value == "":
                if field_map.required:
                    findings.append(
                        Finding.create(
                            module="migration",
                            code="type_incompatible",
                            severity=Severity.ERROR,
                            entity=entity.name,
                            entity_id=record_key,
                            message="Required value is missing for the target field.",
                            evidence={
                                "target_field": target,
                                "required": True,
                                "line": line,
                            },
                            remediation="Fill the source value or drop the required flag.",
                            discriminator=f"value\0{entity.target_module}\0{target}\0{record_key}",
                        )
                    )
                continue
            reason = _check_value(meta, value)
            if reason == "too_long":
                findings.append(
                    Finding.create(
                        module="migration",
                        code="value_too_long",
                        severity=Severity.ERROR,
                        entity=entity.name,
                        entity_id=record_key,
                        message="Value exceeds the target field length.",
                        evidence={
                            "target_field": target,
                            "max": meta.length,
                            "actual_length": len(value),
                            "line": line,
                        },
                        remediation="Shorten the source value or widen the target field.",
                        discriminator=f"value\0{entity.target_module}\0{target}\0{record_key}",
                    )
                )
            elif reason == "not_in_picklist":
                findings.append(
                    Finding.create(
                        module="migration",
                        code="picklist_value_missing",
                        severity=Severity.ERROR,
                        entity=entity.name,
                        entity_id=record_key,
                        message="Value is not an allowed picklist value in the target.",
                        evidence={
                            "target_field": target,
                            "allowed_count": len(meta.pick_list_values),
                            "line": line,
                        },
                        remediation="Add the picklist value to the target or map it to one.",
                        discriminator=f"value\0{entity.target_module}\0{target}\0{record_key}",
                    )
                )
            elif reason == "bad_syntax":
                findings.append(
                    Finding.create(
                        module="migration",
                        code="type_incompatible",
                        severity=Severity.ERROR,
                        entity=entity.name,
                        entity_id=record_key,
                        message="Value type does not fit the target field type.",
                        evidence={
                            "target_field": target,
                            "target_type": meta.data_type,
                            "line": line,
                        },
                        remediation="Fix the source value or adjust the mapping transform.",
                        discriminator=f"value\0{entity.target_module}\0{target}\0{record_key}",
                    )
                )
    for api_name, meta in fields.items():
        if meta.system_mandatory and api_name not in entity.fields:
            findings.append(
                Finding.create(
                    module="migration",
                    code="mandatory_field_unmapped",
                    severity=Severity.ERROR,
                    entity=entity.name,
                    entity_id=api_name,
                    message="Mandatory target field has no mapping.",
                    evidence={"target_module": entity.target_module, "target_field": api_name},
                    remediation="Map a source column to the mandatory field.",
                    discriminator=f"mapping\0{entity.target_module}\0{api_name}",
                )
            )
    for target in entity.fields:
        meta = fields.get(target)
        if meta is None:
            continue
        # Record lookups need a resolution entry; owner fields resolve
        # through target users instead (TK-MIG-F7), never through entities.
        if meta.data_type.casefold() == "lookup" and target not in entity.lookups:
            findings.append(
                Finding.create(
                    module="migration",
                    code="lookup_unresolvable",
                    severity=Severity.REVIEW,
                    entity=entity.name,
                    entity_id=target,
                    message="Lookup target field has no entity resolution in the mapping.",
                    evidence={"target_module": entity.target_module, "target_field": target},
                    remediation="Add a lookups entry resolving this field to a mapped entity.",
                    discriminator=f"mapping\0{entity.target_module}\0{target}",
                )
            )
    # Unique collisions across the sampled batch (fingerprints only).
    # The declared external ID is unique by definition, even when it has
    # no fields entry of its own (it usually does not).
    external_extra: tuple[str, str] | None = None
    if entity.external_id is not None and entity.external_id.field not in entity.fields:
        if entity.external_id.from_col in header:
            external_extra = (entity.external_id.field, entity.external_id.from_col)
    unique_targets = [
        target
        for target, field_map in entity.fields.items()
        if fields.get(target) is not None
        and (
            fields[target].unique
            or target == "Email"
            or (entity.external_id is not None and target == entity.external_id.field)
        )
    ]
    for target in unique_targets:
        seen: dict[str, tuple[str, int]] = {}
        for (line, row), record_key in zip(sample_rows, record_keys, strict=True):
            value, failed = mapped_value(entity, target, row)
            if failed is not None or value is None or value == "":
                continue
            key = value.casefold()
            if key in seen:
                fingerprint = _value_fingerprint(value)
                prior_key, prior_line = seen[key]
                for other_key, other_line in ((prior_key, prior_line), (record_key, line)):
                    findings.append(
                        Finding.create(
                            module="migration",
                            code="unique_field_collision_in_batch",
                            severity=Severity.ERROR,
                            entity=entity.name,
                            entity_id=other_key,
                            message="Two batch rows share one unique target value.",
                            evidence={
                                "target_field": target,
                                "value_fingerprint": fingerprint,
                                "line": other_line,
                            },
                            remediation="Deduplicate the source rows before import.",
                            discriminator=f"value\0{entity.target_module}\0{target}\0{other_key}",
                        )
                    )
            else:
                seen[key] = (record_key, line)
    if external_extra is not None:
        ext_field, ext_col = external_extra
        seen_ext: dict[str, tuple[str, int]] = {}
        for (line, row), record_key in zip(sample_rows, record_keys, strict=True):
            raw = (row.get(ext_col) or "").strip()
            if not raw:
                continue
            key = raw.casefold()
            if key in seen_ext:
                fingerprint = _value_fingerprint(raw)
                prior_key, prior_line = seen_ext[key]
                for other_key, other_line in ((prior_key, prior_line), (record_key, line)):
                    findings.append(
                        Finding.create(
                            module="migration",
                            code="unique_field_collision_in_batch",
                            severity=Severity.ERROR,
                            entity=entity.name,
                            entity_id=other_key,
                            message="Two batch rows share one unique target value.",
                            evidence={
                                "target_field": ext_field,
                                "value_fingerprint": fingerprint,
                                "line": other_line,
                            },
                            remediation="Deduplicate the source rows before import.",
                            discriminator=f"value\0{entity.target_module}\0{ext_field}\0{other_key}",
                        )
                    )
            else:
                seen_ext[key] = (record_key, line)
    return findings


def validate_mapping(
    doc: MappingDoc,
    metadata: TargetMetadata,
    headers: dict[str, list[str]],
    samples: dict[str, list[tuple[int, dict[str, str]]]],
) -> list[Finding]:
    """Validate every mapped entity; unknown modules yield no value checks.

    An entity whose target module has no metadata still gets mapping-level
    structure (unknown fields cannot be proven), so an empty metadata set
    degrades to mandatory/lookup silence rather than false errors: fields
    simply cannot be judged. In practice the CLI fails earlier (exit 1)
    when *no* module metadata loaded at all.
    """
    findings: list[Finding] = []
    for entity in doc.entities:
        fields = metadata.fields_for(entity.target_module)
        header = headers.get(entity.name, [])
        sample_rows = samples.get(entity.name, [])[:SAMPLE_ROWS]
        if not fields:
            findings.append(
                Finding.create(
                    module="migration",
                    code="unknown_target_field",
                    severity=Severity.REVIEW,
                    entity=entity.name,
                    entity_id=entity.target_module,
                    message="Target module metadata is unavailable; fields cannot be checked.",
                    evidence={"target_module": entity.target_module},
                    remediation="Provide the target field metadata and re-run.",
                    discriminator=f"module\0{entity.target_module}",
                )
            )
            continue
        findings.extend(validate_entity(entity, fields, header, sample_rows))
    return findings


__all__: list[str] = [
    "BOOLEAN_WORDS",
    "DATE_TYPES",
    "NUMBER_TYPES",
    "SAMPLE_ROWS",
    "STABLE_ID_FALLBACK_COLS",
    "FieldMeta",
    "TargetMetadata",
    "disambiguated_record_keys",
    "mapped_value",
    "metadata_from_cassette_envelope",
    "metadata_from_dir",
    "stable_record_key",
    "validate_entity",
    "validate_mapping",
]
