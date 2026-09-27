"""Unit tests for the dependency graph (TK-CORE-6 scaffold)."""

from __future__ import annotations

import pytest

from zohokit.core.graph import CycleError, DependencyGraph


def test_topo_order_diamond_is_deterministic() -> None:
    graph = DependencyGraph()
    graph.add("deploy", depends_on=["migrate", "validate"])
    graph.add("migrate", depends_on=["extract"])
    graph.add("validate", depends_on=["extract"])
    graph.add("extract")
    assert graph.topo_order() == ["extract", "migrate", "validate", "deploy"]


def test_self_loop_and_cycle_reported() -> None:
    graph = DependencyGraph()
    graph.add("a", depends_on=["b"])
    graph.add("b", depends_on=["a"])
    cycles = graph.cycles()
    assert len(cycles) >= 1
    with pytest.raises(CycleError):
        graph.topo_order()


def test_missing_reports_undeclared_only() -> None:
    graph = DependencyGraph()
    graph.add("workflow", depends_on=["field:Stage", "field:Amount"])
    graph.add("field:Stage")
    assert graph.missing() == {"field:Amount"}
    assert graph.missing(known=["field:Amount"]) == set()


def test_disconnected_components_all_appear() -> None:
    graph = DependencyGraph()
    graph.add("b")
    graph.add("a")
    assert graph.topo_order() == ["a", "b"]


def test_cycles_are_capped() -> None:
    graph = DependencyGraph()
    nodes = [f"n-{index}" for index in range(6)]
    for left in nodes:
        for right in nodes:
            if left != right:
                graph.add(left, depends_on=[right])
    assert len(graph.cycles(limit=3)) == 3
