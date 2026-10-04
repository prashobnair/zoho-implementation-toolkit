"""Manifest model v2: typed config components with attributes (TK-REL-1).

Legacy v1 items (``{kind, name, depends_on?}``) validate as-is: every v2
field beyond ``kind``/``name`` has a default. Unknown kinds are rejected
(fail closed); experimental kinds are accepted but flagged downstream
with an ``experimental_kind`` finding.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from zohokit.core.ids import canonical_json, fingerprint

MANIFEST_VERSION = 2

#: Kinds carried over from v1 plus the v2 additions.
KINDS_V2: frozenset[str] = frozenset(
    {
        "field",
        "layout",
        "workflow",
        "validation",
        "function",
        "webhook",
        "layout_rule",
        "custom_button",
        "picklist_value",
        "blueprint",
        "client_script",
        "role",
        "profile_permission",
    }
)

#: Kinds whose Zoho API surface is still unverified: accepted in
#: manifests, always reported, never block on their own.
EXPERIMENTAL_KINDS: frozenset[str] = frozenset({"blueprint", "client_script", "profile_permission"})


class Component(BaseModel):
    """One config component: identity plus comparable attributes."""

    model_config = ConfigDict(frozen=True)

    kind: str
    name: str = Field(min_length=1)
    module: str = ""
    api_name: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    source_env: str = ""

    def component_id(self) -> str:
        """Stable ``kind:name`` identity used for indexing and finding IDs."""
        return f"{self.kind}:{self.name}"

    def component_hash(self) -> str:
        """Per-component hash over canonical JSON (order-independent).

        ``source_env`` is provenance, not config: the same component in
        two environments hashes identically so cross-env diffs stay clean.
        """
        payload = self.model_dump(mode="json")
        payload.pop("source_env", None)
        return fingerprint([{"kind": "component", "name": canonical_json(payload)}])


class Manifest(BaseModel):
    """A versioned, sorted component set (one snapshot or diff side)."""

    model_config = ConfigDict(frozen=True)

    version: Literal[2] = 2
    source_env: str = ""
    components: list[Component] = Field(default_factory=list)


def coerce_component(raw: Any) -> Component:
    """Validate one manifest item (v1 or v2 shape); reject unknown kinds."""
    component = Component.model_validate(raw)
    if component.kind not in KINDS_V2:
        raise ValueError(f"unknown component kind {component.kind!r}")
    for dep in component.depends_on:
        if not isinstance(dep, str) or not dep:
            raise ValueError("depends_on must be a non-empty string list")
    return component


def coerce_manifest(raw: Any, *, source_env: str = "") -> Manifest:
    """Validate a component list (or ``{"components": [...]}``) into a Manifest."""
    items = raw.get("components", raw) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("manifest must be a component list")
    components = sorted(
        (coerce_component(item) for item in items),
        key=lambda item: (item.kind, item.name),
    )
    seen = {item.component_id() for item in components}
    if len(seen) != len(components):
        raise ValueError("duplicate component")
    env = raw.get("source_env", source_env) if isinstance(raw, dict) else source_env
    return Manifest(source_env=str(env or ""), components=components)


def manifest_fingerprint(manifest: Manifest) -> str:
    """Permutation-invariant fingerprint over per-component hashes (TK-FIX-1)."""
    ordered = sorted(component.component_hash() for component in manifest.components)
    return fingerprint([{"kind": "hash", "name": digest} for digest in ordered])


def is_v2_item(raw: Any) -> bool:
    """Whether a raw manifest item uses v2-only surface."""
    if not isinstance(raw, dict):
        return False
    if raw.get("kind") in KINDS_V2 and raw.get("kind") not in {
        "field",
        "layout",
        "workflow",
        "validation",
        "function",
        "webhook",
    }:
        return True
    return any(key in raw for key in ("attributes", "module", "api_name", "source_env"))


__all__: list[str] = [
    "EXPERIMENTAL_KINDS",
    "KINDS_V2",
    "MANIFEST_VERSION",
    "Component",
    "Manifest",
    "coerce_component",
    "coerce_manifest",
    "is_v2_item",
    "manifest_fingerprint",
]
