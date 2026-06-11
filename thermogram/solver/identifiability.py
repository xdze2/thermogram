"""Structural identifiability analysis for thermogram RC models.

Finds groups of resistance parameters that are not individually identifiable
from the state vector — only their aggregate (parallel or series combination)
is observable.

The result is a list of groups (each a list of param keys).  Params in the
same group share one free log-scale multiplier during fitting; their ratio is
held fixed at their nominal values.  Singleton groups are individually free.

Only resistance R fields are grouped; C (mass) and gain (source) are always
individually free.

Currently handles the common case: parallel resistors between the same pair
of non-resistance nodes.  Series chains through intermediate resistance nodes
(no mass in between) are detected as a single path and each segment left
individually free but noted — series R values simply sum, so individually they
are not identifiable either, but the present implementation is conservative
and only groups the parallel case, which is the dominant issue in practice.
"""

from __future__ import annotations

from collections import defaultdict


def group_params(atomic_model: dict, param_keys: list[str]) -> list[list[str]]:
    """Group unidentifiable resistance parameters from topology.

    Parameters
    ----------
    atomic_model:
        Atomic model dict (nodes + edges).
    param_keys:
        List of param keys in 'node_id.field' format that are *free* for
        fitting.  Only keys whose node is a resistance and whose field is 'R'
        are candidates for grouping; all others become singleton groups.

    Returns
    -------
    groups:
        List of groups.  Each group is a list of param keys.  Keys within a
        group share one log-scale multiplier (their ratio stays fixed at
        nominals).  Singletons are groups of length 1.
        The order of groups matches the order of the first key in each group
        as it appears in param_keys.
    """
    nodes = {n["id"]: n for n in atomic_model["nodes"]}

    # Build adjacency (undirected)
    neighbours: dict[str, list[str]] = defaultdict(list)
    for edge in atomic_model["edges"]:
        a, b = edge["from"], edge["to"]
        neighbours[a].append(b)
        neighbours[b].append(a)

    def is_resistance(nid: str) -> bool:
        return nodes[nid]["kind"] == "resistance"

    # For each free resistance R param, find the pair of non-resistance
    # endpoints its series-chain connects.
    # A resistance node may sit in a chain: non-R → R → R → … → non-R.
    # We walk both directions until we hit a non-resistance node.

    def chain_endpoints(res_id: str) -> tuple[str, str] | None:
        """Return the two non-resistance endpoints of the chain containing res_id."""
        ends = []
        for start_nbr in neighbours[res_id]:
            # Walk away from res_id through resistance nodes
            prev, cur = res_id, start_nbr
            while is_resistance(cur):
                nexts = [n for n in neighbours[cur] if n != prev]
                if len(nexts) != 1:
                    return None  # branching chain — cannot determine endpoints
                prev, cur = cur, nexts[0]
            ends.append(cur)
        if len(ends) != 2:
            return None
        a, b = ends
        return (min(a, b), max(a, b))

    # Collect free resistance R keys and their endpoint pairs
    res_R_keys: list[str] = []
    for key in param_keys:
        parts = key.split(".", 1)
        if len(parts) == 2:
            node_id, field = parts
            if node_id in nodes and nodes[node_id]["kind"] == "resistance" and field == "R":
                res_R_keys.append(key)

    # Map endpoint pair → list of param keys whose chain connects those endpoints
    pair_to_keys: dict[tuple[str, str], list[str]] = defaultdict(list)
    key_to_pair: dict[str, tuple[str, str] | None] = {}

    for key in res_R_keys:
        node_id = key.split(".", 1)[0]
        pair = chain_endpoints(node_id)
        key_to_pair[key] = pair
        if pair is not None:
            pair_to_keys[pair].append(key)

    # Build groups: parallel resistors (same endpoint pair, more than one key)
    # become one group; others are singletons.
    assigned: set[str] = set()
    groups: list[list[str]] = []

    for key in param_keys:
        if key in assigned:
            continue
        if key not in res_R_keys:
            # C, gain, or non-resistance R — always singleton
            groups.append([key])
            assigned.add(key)
            continue

        pair = key_to_pair.get(key)
        if pair is None:
            groups.append([key])
            assigned.add(key)
            continue

        parallel = pair_to_keys[pair]  # all free R keys on parallel paths
        if len(parallel) == 1:
            groups.append([key])
            assigned.add(key)
        else:
            # Emit the whole parallel group once, in param_keys order
            group = [k for k in param_keys if k in parallel]
            groups.append(group)
            assigned.update(group)

    return groups
