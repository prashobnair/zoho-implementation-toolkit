"""Dependency inference over manifest components (TK-REL-3).

Declared edges come from ``depends_on``. Heuristic edges come from a
static text scan: string attributes of layouts, workflows, webhooks and
functions are searched for ``api_name`` tokens of field components in
the same manifest. Heuristic edges are labeled as such and reported
with a ``heuristic_dependency`` info finding; they never block.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from zohokit.modules.release.manifest import Component

Confidence = Literal["declared", "heuristic"]


@dataclass(frozen=True)
class Edge:
    """One directed dependency between component IDs (``kind:name``)."""

    source: str
    target: str
    via: str
    confidence: Confidence


#: String attributes scanned for ``api_name`` tokens, per kind. Everything
#: else (ids, flags, counts) is structural and never scanned.
SCANNED_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    "layout": ("fields", "sections", "rules"),
    "layout_rule": ("criteria", "fields"),
    "workflow": ("trigger_fields", "criteria_fields", "target_fields", "criteria"),
    "webhook": ("url", "body", "params"),
    "function": ("source",),
    "validation": ("criteria", "formula"),
    "custom_button": ("criteria",),
    "blueprint": ("criteria",),
}


def _string_attributes(component: Component) -> list[tuple[str, str]]:
    """Scannable ``(attribute, text)`` pairs for one component."""
    names = SCANNED_ATTRIBUTES.get(component.kind, ())
    found: list[tuple[str, str]] = []
    for name in names:
        value = component.attributes.get(name)
        if isinstance(value, str) and value:
            found.append((name, value))
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            joined = " ".join(item for item in value if item)
            if joined:
                found.append((name, joined))
    return found


def infer_edges(components: list[Component]) -> list[Edge]:
    """Declared plus heuristic edges, sorted for determinism.

    Heuristic rule: when a scanned string attribute of component A
    contains the ``api_name`` (or full ``name``) of a field component B
    in the same manifest, A heuristically depends on B. Matching is
    case-sensitive token containment; empty tokens never match.
    """
    fields = sorted(
        (item for item in components if item.kind == "field" and (item.api_name or item.name)),
        key=lambda entry: entry.component_id(),
    )
    edges: dict[tuple[str, str, str, str], Edge] = {}
    for item in sorted(components, key=lambda entry: entry.component_id()):
        for dep in sorted(set(item.depends_on)):
            edges[(item.component_id(), dep, "depends_on", "declared")] = Edge(
                source=item.component_id(), target=dep, via="depends_on", confidence="declared"
            )
        for attribute, text in _string_attributes(item):
            for target in fields:
                if target.component_id() == item.component_id():
                    continue
                for token in (target.api_name, target.name):
                    if token and token in text:
                        key = (item.component_id(), target.component_id(), attribute, "heuristic")
                        edges[key] = Edge(
                            source=item.component_id(),
                            target=target.component_id(),
                            via=attribute,
                            confidence="heuristic",
                        )
                        break
    return sorted(edges.values(), key=lambda edge: (edge.source, edge.target, edge.via))


__all__: list[str] = ["SCANNED_ATTRIBUTES", "Confidence", "Edge", "infer_edges"]
