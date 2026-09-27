"""Dependency graphs: missing refs, cycle detection, topo sort (TK-CORE-6)."""

from __future__ import annotations

from collections.abc import Iterable

MAX_CYCLES = 10


class CycleError(ValueError):
    """Raised by :meth:`DependencyGraph.topo_order` when a cycle exists."""

    def __init__(self, cycle: list[str]) -> None:
        super().__init__(f"dependency cycle: {' -> '.join(cycle)}")
        self.cycle = cycle


def _canonical_cycle(cycle: list[str]) -> list[str]:
    """Rotate a closed cycle so the smallest node comes first."""
    core = cycle[:-1]
    pivot = core.index(min(core))
    rotated = core[pivot:] + core[:pivot]
    return [*rotated, rotated[0]]


class DependencyGraph:
    """A small deterministic dependency graph over named components."""

    def __init__(self) -> None:
        self._edges: dict[str, set[str]] = {}
        self._explicit: set[str] = set()

    def add(self, node: str, depends_on: Iterable[str] = ()) -> None:
        """Declare ``node`` with edges to each entry of ``depends_on``."""
        self._explicit.add(node)
        self._edges.setdefault(node, set()).update(depends_on)
        for dep in depends_on:
            self._edges.setdefault(dep, set())

    def nodes(self) -> list[str]:
        """All known nodes in sorted order."""
        return sorted(self._edges)

    def missing(self, known: Iterable[str] = ()) -> set[str]:
        """Referenced dependencies that were never declared.

        ``known`` lists externally provided names (for example live
        metadata) that should not count as missing.
        """
        provided = set(known)
        referenced = {dep for deps in self._edges.values() for dep in deps}
        return {dep for dep in referenced if dep not in self._explicit and dep not in provided}

    def cycles(self, *, limit: int = MAX_CYCLES) -> list[list[str]]:
        """Find elementary cycles (capped at ``limit``).

        Each cycle is canonicalized: rotated so the smallest node comes
        first, so rotations of one cycle collapse to a single entry.
        """
        found: list[list[str]] = []
        seen: set[tuple[str, ...]] = set()

        def visit(start: str, current: str, stack: list[str]) -> None:
            if len(found) >= limit:
                return
            for dep in sorted(self._edges.get(current, ())):
                if dep == start:
                    cycle = _canonical_cycle([*stack, start])
                    if tuple(cycle) not in seen:
                        seen.add(tuple(cycle))
                        found.append(cycle)
                elif dep not in stack:
                    visit(start, dep, [*stack, dep])
                    if len(found) >= limit:
                        return

        for node in sorted(self._edges):
            visit(node, node, [node])
            if len(found) >= limit:
                break
        return found

    def topo_order(self) -> list[str]:
        """Deterministic topological order (ties broken by name).

        Dependencies come before dependents. Raises :class:`CycleError`
        when the graph has a cycle.
        """
        visited: dict[str, str] = {}
        order: list[str] = []
        stack: list[str] = []

        def visit(node: str) -> None:
            state = visited.get(node)
            if state == "done":
                return
            if state == "visiting":
                raise CycleError([*stack[stack.index(node) :], node])
            visited[node] = "visiting"
            stack.append(node)
            for dep in sorted(self._edges.get(node, ())):
                visit(dep)
            stack.pop()
            visited[node] = "done"
            order.append(node)

        for node in sorted(self._edges):
            visit(node)
        return order
