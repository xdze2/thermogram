"""Graph → state-space assembly for thermogram schema v0.3.

Resistance nodes are eliminated by condensing their conductance into direct
G=1/R links between neighbours. Series chains (R→R→…) are folded by summing
R values before inverting.

Returns an AssembledSystem with continuous-time matrices:
    dx/dt = A x + B_boundary u_b + B_source u_s
where x = temperatures of mass nodes, u_b = boundary temperatures,
u_s = source signals.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class AssembledSystem:
    A: np.ndarray           # [n_mass × n_mass]
    B_boundary: np.ndarray  # [n_mass × n_boundary]
    B_source: np.ndarray    # [n_mass × n_source]
    mass_ids: list[str]
    boundary_ids: list[str]
    source_ids: list[str]


def assemble(atomic_model: dict) -> AssembledSystem:
    """Assemble an atomic model dict into state-space matrices."""
    nodes = {n["id"]: n for n in atomic_model["nodes"]}

    # Build adjacency for resistance nodes as undirected graph
    # neighbours[node_id] = list of neighbour node_ids (via raw edges)
    neighbours: dict[str, list[str]] = {nid: [] for nid in nodes}
    for edge in atomic_model["edges"]:
        a, b = edge["from"], edge["to"]
        neighbours[a].append(b)
        neighbours[b].append(a)

    # Eliminate resistance nodes: find conductance G between non-resistance nodes.
    # We do a DFS through chains of resistance nodes to sum R values transitively.
    conductances: dict[tuple[str, str], float] = {}  # (id_a, id_b) → G, a<b

    def add_conductance(a: str, b: str, G: float) -> None:
        key = (min(a, b), max(a, b))
        conductances[key] = conductances.get(key, 0.0) + G

    def _is_resistance(nid: str) -> bool:
        return nodes[nid]["kind"] == "resistance"

    visited_starts: set[tuple[str, str]] = set()

    for start_id, start_node in nodes.items():
        if _is_resistance(start_id):
            continue  # only start walks from non-resistance nodes
        for nbr in neighbours[start_id]:
            if not _is_resistance(nbr):
                # Direct non-resistance neighbour — but source→mass edges carry
                # no conductance; only mass↔boundary and mass↔mass matter here.
                continue
            if (start_id, nbr) in visited_starts:
                continue
            # Walk the resistance chain from start_id through nbr
            # accumulating R until we reach another non-resistance node.
            prev = start_id
            cur = nbr
            R_total = 0.0
            while _is_resistance(cur):
                R_total += nodes[cur]["R"]
                nexts = [n for n in neighbours[cur] if n != prev]
                if len(nexts) != 1:
                    raise ValueError(
                        f"Resistance node '{cur}' must have exactly 2 edges, "
                        f"got neighbours: {neighbours[cur]}"
                    )
                prev, cur = cur, nexts[0]
            # cur is now the non-resistance node at the other end
            end_id = cur
            visited_starts.add((start_id, nbr))
            visited_starts.add((end_id, prev))
            add_conductance(start_id, end_id, 1.0 / R_total)

    # Classify non-resistance nodes
    mass_ids = [nid for nid, n in nodes.items() if n["kind"] == "mass"]
    boundary_ids = [nid for nid, n in nodes.items() if n["kind"] == "boundary"]
    source_ids = [nid for nid, n in nodes.items() if n["kind"] == "source"]

    n_mass = len(mass_ids)
    n_boundary = len(boundary_ids)
    n_source = len(source_ids)

    mi = {nid: i for i, nid in enumerate(mass_ids)}
    bi = {nid: i for i, nid in enumerate(boundary_ids)}
    si = {nid: i for i, nid in enumerate(source_ids)}

    A = np.zeros((n_mass, n_mass))
    B_boundary = np.zeros((n_mass, n_boundary))
    B_source = np.zeros((n_mass, n_source))

    for (a, b), G in conductances.items():
        kind_a, kind_b = nodes[a]["kind"], nodes[b]["kind"]

        # mass ↔ mass
        if kind_a == "mass" and kind_b == "mass":
            i, j = mi[a], mi[b]
            C_i = nodes[a]["C"]
            C_j = nodes[b]["C"]
            A[i, i] -= G / C_i
            A[i, j] += G / C_i
            A[j, j] -= G / C_j
            A[j, i] += G / C_j

        # mass ↔ boundary
        elif kind_a == "mass" and kind_b == "boundary":
            i, k = mi[a], bi[b]
            C_i = nodes[a]["C"]
            A[i, i] -= G / C_i
            B_boundary[i, k] += G / C_i

        elif kind_a == "boundary" and kind_b == "mass":
            k, i = bi[a], mi[b]
            C_i = nodes[b]["C"]
            A[i, i] -= G / C_i
            B_boundary[i, k] += G / C_i

    # Source → mass injections (from raw edges, not conductances)
    for edge in atomic_model["edges"]:
        src_id, tgt_id = edge["from"], edge["to"]
        if nodes[src_id]["kind"] == "source" and nodes[tgt_id]["kind"] == "mass":
            i = mi[tgt_id]
            s = si[src_id]
            gain = nodes[src_id]["gain"]
            C_i = nodes[tgt_id]["C"]
            B_source[i, s] += gain / C_i

    return AssembledSystem(
        A=A,
        B_boundary=B_boundary,
        B_source=B_source,
        mass_ids=mass_ids,
        boundary_ids=boundary_ids,
        source_ids=source_ids,
    )
