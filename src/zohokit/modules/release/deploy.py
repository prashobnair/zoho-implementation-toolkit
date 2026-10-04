"""Deploy order: topological order for adds/changes, reverse for removals (TK-REL-6)."""

from __future__ import annotations

from dataclasses import dataclass, field

from zohokit.core.graph import CycleError, DependencyGraph
from zohokit.modules.release.diff import ManifestDiff
from zohokit.modules.release.infer import Edge


@dataclass(frozen=True)
class DeployPlan:
    """Ordered component IDs: deploy first, then remove in reverse."""

    deploy: tuple[str, ...] = ()
    removals: tuple[str, ...] = ()
    cycles: tuple[tuple[str, ...], ...] = field(default_factory=tuple)


def plan_deploy(diff: ManifestDiff, edges: list[Edge]) -> DeployPlan:
    """Order ``added``/``changed`` dependencies-first, removals dependents-first.

    Only edges whose both ends are deployed components constrain the
    deploy order; edges into removed or untouched components are noted
    but never order anything. A cycle yields an empty order plus the
    canonical cycle paths (the engine turns them into
    ``dependency_cycle`` findings).
    """
    wanted = set(diff.added) | set(diff.changed)
    graph = DependencyGraph()
    for component_id in sorted(wanted):
        graph.add(component_id)
    for edge in edges:
        if edge.source in wanted and edge.target in wanted:
            graph.add(edge.source, [edge.target])
    cycles = graph.cycles()
    if cycles:
        return DeployPlan(cycles=tuple(tuple(cycle) for cycle in cycles))
    try:
        deploy = [node for node in graph.topo_order() if node in wanted]
    except CycleError as exc:
        return DeployPlan(cycles=(tuple(exc.cycle),))
    gone = set(diff.removed)
    removal_graph = DependencyGraph()
    for component_id in sorted(gone):
        removal_graph.add(component_id)
    for edge in edges:
        if edge.source in gone and edge.target in gone:
            removal_graph.add(edge.source, [edge.target])
    removal_cycles = removal_graph.cycles()
    if removal_cycles:
        combined = list(cycles) + [list(cycle) for cycle in removal_cycles]
        return DeployPlan(cycles=tuple(tuple(cycle) for cycle in combined))
    try:
        removal_order = [node for node in removal_graph.topo_order() if node in gone]
    except CycleError as exc:
        return DeployPlan(cycles=(tuple(exc.cycle),))
    removal_order.reverse()
    return DeployPlan(deploy=tuple(deploy), removals=tuple(removal_order))


__all__: list[str] = ["DeployPlan", "plan_deploy"]
