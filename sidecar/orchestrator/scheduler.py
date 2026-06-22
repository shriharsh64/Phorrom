"""DAG scheduler — builds the subtask graph and computes the ready set.

Problem solved: the dynamic-workflow engine. Given subtasks + their dependencies and which are
already done, return the subtasks whose dependencies are all satisfied (the "ready set"), in a
sensible order. The full orchestrator re-runs this after each batch — that is what makes the
workflow dynamic.

Inputs : a list of Subtask + a set of completed subtask ids.
Outputs: ready Subtasks ordered by value (desc), plus topological ordering helpers.
"""

from __future__ import annotations

import networkx as nx

from .decompose import Subtask


def build_graph(subtasks: list[Subtask]) -> nx.DiGraph:
    g = nx.DiGraph()
    for s in subtasks:
        g.add_node(s.id, subtask=s)
    for s in subtasks:
        for dep in s.depends_on:
            g.add_edge(dep, s.id)  # edge dep -> s (dep must finish first)
    if not nx.is_directed_acyclic_graph(g):
        raise ValueError("subtask graph is not a DAG")
    return g


def topological_order(subtasks: list[Subtask]) -> list[str]:
    return list(nx.topological_sort(build_graph(subtasks)))


def ready_set(subtasks: list[Subtask], done: set[str]) -> list[Subtask]:
    """Subtasks not yet done whose every dependency is done — highest value first."""

    by_id = {s.id: s for s in subtasks}
    ready = [
        s for s in subtasks
        if s.id not in done and all(d in done for d in s.depends_on)
    ]
    ready.sort(key=lambda s: (s.value, s.p_required), reverse=True)
    return [by_id[s.id] for s in ready]


def critical_path_length(subtasks: list[Subtask]) -> int:
    """Longest dependency chain (number of nodes) — a proxy for project depth/critical path."""

    g = build_graph(subtasks)
    return nx.dag_longest_path_length(g) + 1 if g.number_of_nodes() else 0
