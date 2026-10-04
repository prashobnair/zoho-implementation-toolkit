"""Manifest v2 diff: changes plus per-component attribute diffs (TK-REL-4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from zohokit.core.ids import canonical_json
from zohokit.modules.release.manifest import Component

ChangeKind = Literal["added", "removed", "changed"]


@dataclass(frozen=True)
class AttributeChange:
    """One attribute that differs, with before and after values."""

    attribute: str
    before: Any
    after: Any

    def describe(self) -> str:
        """Human ``before → after`` rendering (JSON values, sorted keys)."""
        return f"{self.attribute}: {canonical_json(self.before)} → {canonical_json(self.after)}"


@dataclass(frozen=True)
class ComponentChange:
    """One added, removed or changed component with its attribute diff."""

    component_id: str
    kind: str
    name: str
    change: ChangeKind
    attributes: tuple[AttributeChange, ...] = ()
    before_hash: str = ""
    after_hash: str = ""


@dataclass(frozen=True)
class ManifestDiff:
    """Full before → after comparison."""

    changes: tuple[ComponentChange, ...] = ()
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    attribute_notes: tuple[str, ...] = field(default_factory=tuple)


def _attribute_diff(before: Component, after: Component) -> tuple[AttributeChange, ...]:
    """Per-attribute before → after over the union of attribute names."""
    names = sorted(set(before.attributes) | set(after.attributes))
    out: list[AttributeChange] = []
    for name in names:
        old = before.attributes.get(name)
        new = after.attributes.get(name)
        if canonical_json(old) != canonical_json(new):
            out.append(AttributeChange(attribute=name, before=old, after=new))
    return tuple(out)


def diff_manifests(before: list[Component], after: list[Component]) -> ManifestDiff:
    """Diff two component lists by ``kind:name`` (TK-REL-4).

    Structural identity fields (``module``, ``api_name``) join the
    attribute comparison: a component whose attributes match but whose
    ``api_name`` moved still counts as changed, with the field named
    explicitly. ``source_env`` is provenance and never a change.
    """
    old = {item.component_id(): item for item in before}
    new = {item.component_id(): item for item in after}
    changes: list[ComponentChange] = []
    for component_id in sorted(set(old) | set(new)):
        prior, later = old.get(component_id), new.get(component_id)
        if prior is None and later is not None:
            changes.append(
                ComponentChange(
                    component_id=component_id,
                    kind=later.kind,
                    name=later.name,
                    change="added",
                    after_hash=later.component_hash(),
                )
            )
        elif later is None and prior is not None:
            changes.append(
                ComponentChange(
                    component_id=component_id,
                    kind=prior.kind,
                    name=prior.name,
                    change="removed",
                    before_hash=prior.component_hash(),
                )
            )
        elif prior is not None and later is not None:
            attribute_changes = _attribute_diff(prior, later)
            identity_changes = tuple(
                AttributeChange(
                    attribute=slot, before=getattr(prior, slot), after=getattr(later, slot)
                )
                for slot in ("module", "api_name")
                if getattr(prior, slot) != getattr(later, slot)
            )
            combined = attribute_changes + identity_changes
            if combined or prior.component_hash() != later.component_hash():
                changes.append(
                    ComponentChange(
                        component_id=component_id,
                        kind=later.kind,
                        name=later.name,
                        change="changed",
                        attributes=tuple(sorted(combined, key=lambda entry: entry.attribute)),
                        before_hash=prior.component_hash(),
                        after_hash=later.component_hash(),
                    )
                )
    notes = tuple(
        f"{change.component_id}: {entry.describe()}"
        for change in changes
        for entry in change.attributes
    )
    return ManifestDiff(
        changes=tuple(changes),
        added=tuple(change.component_id for change in changes if change.change == "added"),
        removed=tuple(change.component_id for change in changes if change.change == "removed"),
        changed=tuple(change.component_id for change in changes if change.change == "changed"),
        attribute_notes=notes,
    )


__all__: list[str] = [
    "AttributeChange",
    "ChangeKind",
    "ComponentChange",
    "ManifestDiff",
    "diff_manifests",
]
