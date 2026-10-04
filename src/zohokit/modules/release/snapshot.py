"""Config-as-code snapshots: normalized, sorted, redacted manifests (TK-REL-2).

A snapshot reads the org read-only through the GET-only client (verified
endpoints only: modules, fields, users, org), merges optional
user-exported JSON for kinds without a verified read API, redacts
attribute values, and writes one file per kind. Files carry no
timestamps, so two snapshots of an unchanged org are byte-identical.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from zohokit.connectors.zoho.client import ZohoClient
from zohokit.connectors.zoho.models import FieldsResponse, unwrap_fields
from zohokit.connectors.zoho.readers import read_model
from zohokit.core.ids import canonical_json
from zohokit.core.redact import Redactor
from zohokit.modules.release.manifest import (
    MANIFEST_VERSION,
    Component,
    Manifest,
    coerce_manifest,
)

#: Default CRM modules captured per snapshot.
DEFAULT_SNAPSHOT_MODULES: tuple[str, ...] = ("Leads", "Contacts", "Deals")

#: Snapshot file envelope per kind (no timestamps: byte-identical reruns).
SNAPSHOT_SCHEMA_VERSION = 1


def snapshot_from_client(
    client: ZohoClient,
    *,
    source_env: str,
    modules: tuple[str, ...] = DEFAULT_SNAPSHOT_MODULES,
    extra: list[Component] | None = None,
) -> Manifest:
    """Read verified endpoints and build the manifest (GET-only, budgeted).

    ``field`` components come from ``/crm/v8/settings/fields`` per
    module; ``extra`` carries user-exported components for kinds without
    a verified read API (layouts, workflows, webhooks and the rest).
    Attribute values pass through the shared redactor; IDs survive it.
    """
    components: list[Component] = []
    for module in modules:
        fields = unwrap_fields(
            read_model(
                client,
                "/crm/v8/settings/fields",
                FieldsResponse,
                params={"module": module},
            ).model_dump(),
            endpoint="/crm/v8/settings/fields",
        )
        for entry in fields:
            components.append(_field_component(module, entry, source_env))
    if extra:
        components.extend(extra)
    redactor = Redactor()
    redacted = [
        item.model_copy(update={"attributes": redactor.redact_obj(dict(item.attributes)) or {}})
        for item in components
    ]
    manifest = coerce_manifest(
        [item.model_dump(mode="json") for item in redacted], source_env=source_env
    )
    return manifest


def _field_component(module: str, entry: dict[str, Any], source_env: str) -> Component:
    """One ``field`` component from a settings/fields entry (redacted later)."""
    api_name = str(entry.get("api_name", ""))
    attributes: dict[str, Any] = {}
    for key in (
        "data_type",
        "json_type",
        "field_label",
        "length",
        "mandatory",
        "read_only",
        "system_mandatory",
        "pick_list_values",
        "lookup_module",
        "formula",
    ):
        if key in entry:
            attributes[key] = entry[key]
    depends_on: list[str] = []
    lookup = entry.get("lookup_module")
    if isinstance(lookup, str) and lookup:
        depends_on.append(f"field:{lookup}")
    return Component(
        kind="field",
        name=f"{module}.{api_name}",
        module=module,
        api_name=api_name,
        attributes=attributes,
        depends_on=depends_on,
        source_env=source_env,
    )


def snapshot_files(manifest: Manifest) -> dict[str, str]:
    """Render one canonical file body per kind (sorted, no timestamps)."""
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for item in manifest.components:
        by_kind.setdefault(item.kind, []).append(item.model_dump(mode="json"))
    files: dict[str, str] = {}
    for kind in sorted(by_kind):
        payload = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "manifest_version": MANIFEST_VERSION,
            "source_env": manifest.source_env,
            "kind": kind,
            "components": sorted(by_kind[kind], key=lambda entry: str(entry.get("name", ""))),
        }
        files[f"{kind}.json"] = canonical_json(payload) + "\n"
    return files


def write_snapshot(manifest: Manifest, out_dir: Path) -> list[Path]:
    """Write one file per kind into *out_dir*; return the written paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for filename, body in snapshot_files(manifest).items():
        path = out_dir / filename
        path.write_text(body, encoding="utf-8")
        written.append(path)
    return written


def read_snapshot(approved_dir: Path) -> Manifest:
    """Read every ``*.json`` kind file back into one manifest."""
    components: list[dict[str, Any]] = []
    source_env = ""
    for path in sorted(approved_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"cannot read approved manifest {path}: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("components"), list):
            raise ValueError(f"approved manifest {path} must hold a components list")
        if not source_env:
            source_env = str(payload.get("source_env", ""))
        components.extend(payload["components"])
    return coerce_manifest(components, source_env=source_env)


def snapshot_fingerprint(manifest: Manifest) -> str:
    """Stable content hash for logging (counts and hashes, never values)."""
    return hashlib.sha256(canonical_json(snapshot_files(manifest)).encode("utf-8")).hexdigest()


__all__: list[str] = [
    "DEFAULT_SNAPSHOT_MODULES",
    "SNAPSHOT_SCHEMA_VERSION",
    "read_snapshot",
    "snapshot_files",
    "snapshot_fingerprint",
    "snapshot_from_client",
    "write_snapshot",
]
