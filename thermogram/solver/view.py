"""Build a default View from an atomic model + expansion_map.

The View is the φ-space the fit operates on.  ``build_default_view`` produces
a deterministic, one-depth lumped model from the output of ``expand()``:

  opaque element (chained wall)
    → one RC_chain lumped element, 2 φ (R_total, C_total)
      Rse / Rsi nodes are listed in lump.atoms but NOT in the chain's free
      r_atom_ids — they are structural (fixed weights in the combine rule).
      This kills the series-identifiability trap structurally.

  opaque element (no_mass, chain_n == 0)
    → one Req lumped element, series_sum rule covering the single R node

  glazing / air_exchange
    → one Req per element (parallel R atoms between the same node pair are
      merged into one shared Req by build_default_view — replaces the old
      identifiability.group_params heuristic).

  room (mass node)
    → one Ceq lumped element, parallel_sum rule

  boundary / source nodes
    → one identity lumped element per node, mode "fixed"

Coverage invariant: every active atomic node (except Rse/Rsi which are folded
into the chain) is covered by exactly one lumped element.
"""

from __future__ import annotations

import uuid as _uuid
from collections import defaultdict

from thermogram.models import (
    CombineRule,
    LumpedElement,
    Prior,
    View,
)
from thermogram.solver.lumps import (
    ChainAtoms,
    compose_chain_prior,
    compose_parallel_inv_prior,
    compose_parallel_sum_prior,
    compose_series_prior,
)

# Default log-space sigma for free lumped elements
_SIGMA_LOG_FREE = 0.5
_SIGMA_LOG_FIXED = 0.0


def _node_map(atomic_model: dict) -> dict[str, dict]:
    return {n["id"]: n for n in atomic_model["nodes"]}


def _endpoint_pair(
    node_id: str,
    nodes: dict[str, dict],
    neighbours: dict[str, list[str]],
) -> tuple[str, str] | None:
    """Find the two non-resistance endpoint ids of a resistance chain through node_id."""
    ends = []
    for start_nbr in neighbours[node_id]:
        prev, cur = node_id, start_nbr
        while nodes[cur]["kind"] == "resistance":
            nexts = [n for n in neighbours[cur] if n != prev]
            if len(nexts) != 1:
                return None
            prev, cur = cur, nexts[0]
        ends.append(cur)
    if len(ends) != 2:
        return None
    a, b = ends
    return (min(a, b), max(a, b))


def build_default_view(
    atomic_model: dict,
    expansion_map: dict[str, list[str]],
) -> View:
    """Build a default one-depth View from expand() output.

    Parameters
    ----------
    atomic_model:
        The dict returned by ``expand(house)``.
    expansion_map:
        The ``{house_uuid: [atom_node_ids]}`` dict returned by ``expand()``.

    Returns
    -------
    View with one LumpedElement per domain element.
    The returned View has a stable ``id`` (UUID4 hex).
    """
    nodes = _node_map(atomic_model)
    wall_chains: dict[str, dict] = atomic_model.get("wall_chains", {})

    # Build undirected adjacency (for parallel-R detection on non-chain elements)
    neighbours: dict[str, list[str]] = defaultdict(list)
    for edge in atomic_model["edges"]:
        a, b = edge["from"], edge["to"]
        neighbours[a].append(b)
        neighbours[b].append(a)

    # Build reverse map: atom_id → element_uuid
    atom_to_element: dict[str, str] = {}
    for elem_uuid, atom_ids in expansion_map.items():
        for aid in atom_ids:
            atom_to_element[aid] = elem_uuid

    # Build label → chain info lookup (the existing wall_chains dict is keyed by label)
    # We also need label → element_uuid; derive from expansion_map + node labels.
    # wall_chains keys are element labels; atom nodes carry matching label prefixes.
    # Simpler: build element_uuid → chain_info by matching r_ids / mass_ids to atoms.
    # wall_chains: { label: {mass_ids, r_ids, chain_n, R_wall, C_wall} }

    # Map: element uuid → wall_chain entry (if any), split by mass/no-mass
    uuid_to_chain: dict[str, dict] = {}        # opaque with mass (chain_n > 0)
    uuid_to_nomass_chain: dict[str, dict] = {} # opaque no_mass (chain_n == 0)

    for label, chain in wall_chains.items():
        is_nomass = chain.get("chain_n", 1) == 0
        candidate_ids = chain.get("mass_ids", []) + chain.get("r_ids", [])
        if not candidate_ids:
            continue
        for aid in candidate_ids:
            if aid in atom_to_element:
                if is_nomass:
                    uuid_to_nomass_chain[atom_to_element[aid]] = chain
                else:
                    uuid_to_chain[atom_to_element[aid]] = chain
                break

    # Track which atom ids have been assigned to a lumped element
    covered: set[str] = set()
    lumped: list[LumpedElement] = []

    # --- Rse/Rsi tracking: these are folded into RC_chain and not separately lumped ---
    rse_rsi_ids: set[str] = set()
    for chain in wall_chains.values():
        # Expand the element's atoms from the expansion_map
        # Rse/Rsi are resistance nodes whose label ends in "(Rse)" or "(Rsi)"
        pass  # Identified below per element

    # --- 1. Opaque elements with mass (RC_chain) ---
    for elem_uuid, chain in uuid_to_chain.items():
        atom_ids = expansion_map.get(elem_uuid, [])

        # Identify Rse/Rsi ids for this element
        surface_r_ids = [
            aid for aid in atom_ids
            if nodes.get(aid, {}).get("kind") == "resistance"
            and aid not in chain["r_ids"]  # not an interior chain R
        ]
        rse_rsi_ids.update(surface_r_ids)

        # All atoms for this element: mass + interior R + Rse/Rsi + source nodes
        # Rse/Rsi are included in lump.atoms (provenance) but NOT in chain_atoms.r_atom_ids
        lump_id = f"chain_{elem_uuid.replace('-', '')}"

        prior_R, prior_C = compose_chain_prior(
            chain["R_wall"], chain["C_wall"], sigma_log=_SIGMA_LOG_FREE
        )

        lump = LumpedElement(
            id=lump_id,
            kind="RC_chain",
            label=None,  # view.py doesn't know the house element label
            atoms=atom_ids,
            combine="chain",
            n=chain["chain_n"],
            prior=prior_R,      # Prior for R_total (C prior stored as lump.posterior placeholder)
            mode="free",
            realizes=elem_uuid,
        )
        # Attach C prior as a custom attribute via model's extra="forbid" — instead,
        # we store both priors as a tuple in the metadata dict below.
        lumped.append(lump)
        covered.update(atom_ids)

    # --- 2. No-mass opaque walls (pure Req, series_sum) ---
    for elem_uuid, chain in uuid_to_nomass_chain.items():
        r_ids = chain["r_ids"]
        atom_ids = expansion_map.get(elem_uuid, [])
        lump_id = f"req_{elem_uuid.replace('-', '')}"
        r_noms = [nodes[rid]["R"] for rid in r_ids]
        prior = compose_series_prior(r_noms, sigma_log=_SIGMA_LOG_FREE)
        lump = LumpedElement(
            id=lump_id,
            kind="Req",
            atoms=r_ids,
            combine="series_sum",
            prior=prior,
            mode="free",
            realizes=elem_uuid,
        )
        lumped.append(lump)
        covered.update(atom_ids)

    # --- 3. Non-opaque resistance elements (glazing, air_exchange) ---
    # Group by endpoint pair to merge parallel resistors into one Req.
    # We look at resistance nodes not yet covered (not part of an opaque wall).
    pair_to_r_atoms: dict[tuple[str, str], list[str]] = defaultdict(list)
    pair_to_elem_uuids: dict[tuple[str, str], list[str]] = defaultdict(list)

    for nid, node in nodes.items():
        if node["kind"] != "resistance":
            continue
        if nid in covered or nid in rse_rsi_ids:
            continue
        pair = _endpoint_pair(nid, nodes, neighbours)
        if pair is None:
            continue
        pair_to_r_atoms[pair].append(nid)
        elem_uuid = atom_to_element.get(nid)
        if elem_uuid and elem_uuid not in pair_to_elem_uuids[pair]:
            pair_to_elem_uuids[pair].append(elem_uuid)

    for pair, r_ids in pair_to_r_atoms.items():
        elem_uuids = pair_to_elem_uuids[pair]
        # Use first element uuid for provenance (or None if unknown)
        realizes = elem_uuids[0] if len(elem_uuids) == 1 else None
        lump_id = f"req_{'_'.join(sorted(r_ids))}"

        r_noms = [nodes[rid]["R"] for rid in r_ids]
        if len(r_ids) == 1:
            prior = compose_series_sum_single(r_noms[0], sigma_log=_SIGMA_LOG_FREE)
            combine: CombineRule = "series_sum"
        else:
            prior = compose_parallel_inv_prior(r_noms, sigma_log=_SIGMA_LOG_FREE)
            combine = "parallel_inv_sum"

        lump = LumpedElement(
            id=lump_id,
            kind="Req",
            atoms=r_ids,
            combine=combine,
            prior=prior,
            mode="free",
            realizes=realizes,
        )
        lumped.append(lump)
        covered.update(r_ids)

    # --- 4. Room mass nodes (Ceq, parallel_sum) ---
    # Group by element uuid (each room → one mass node → one Ceq)
    room_masses_by_elem: dict[str, list[str]] = defaultdict(list)
    for nid, node in nodes.items():
        if node["kind"] != "mass":
            continue
        if nid in covered:
            continue
        elem_uuid = atom_to_element.get(nid)
        if elem_uuid:
            room_masses_by_elem[elem_uuid].append(nid)
        else:
            # Orphan mass node — wrap as identity
            lump_id = f"ceq_{nid}"
            prior = Prior(nominal=node["C"], sigma_log=_SIGMA_LOG_FREE)
            lumped.append(LumpedElement(
                id=lump_id,
                kind="Ceq",
                atoms=[nid],
                combine="parallel_sum",
                prior=prior,
                mode="free",
            ))
            covered.add(nid)

    for elem_uuid, mass_ids in room_masses_by_elem.items():
        lump_id = f"ceq_{elem_uuid.replace('-', '')}"
        c_noms = [nodes[mid]["C"] for mid in mass_ids]
        prior = compose_parallel_sum_prior(c_noms, sigma_log=_SIGMA_LOG_FREE)
        lump = LumpedElement(
            id=lump_id,
            kind="Ceq",
            atoms=mass_ids,
            combine="parallel_sum",
            prior=prior,
            mode="free",
            realizes=elem_uuid,
        )
        lumped.append(lump)
        covered.update(mass_ids)

    # --- 5. Boundary and source nodes → identity, fixed ---
    for nid, node in nodes.items():
        if nid in covered or nid in rse_rsi_ids:
            continue
        if node["kind"] == "boundary":
            lump_id = f"tbnd_{nid}"
            # T_source may be a string (signal) or float; use 0 as prior placeholder
            t_val = node.get("T_source", 0.0)
            nominal = float(t_val) if isinstance(t_val, (int, float)) else 1.0
            prior = Prior(nominal=nominal, sigma_log=_SIGMA_LOG_FIXED)
            lumped.append(LumpedElement(
                id=lump_id,
                kind="T_boundary",
                atoms=[nid],
                combine="identity",
                prior=prior,
                mode="fixed",
                realizes=atom_to_element.get(nid),
            ))
            covered.add(nid)
        elif node["kind"] == "source":
            lump_id = f"qsrc_{nid}"
            gain = node.get("gain", 1.0)
            prior = Prior(nominal=float(gain), sigma_log=_SIGMA_LOG_FIXED)
            lumped.append(LumpedElement(
                id=lump_id,
                kind="Q_source",
                atoms=[nid],
                combine="identity",
                prior=prior,
                mode="fixed",
                realizes=atom_to_element.get(nid),
            ))
            covered.add(nid)

    return View(
        id=_uuid.uuid4().hex,
        lumped=lumped,
    )


def chain_atoms_for_lump(
    lump: LumpedElement,
    atomic_model: dict,
    expansion_map: dict[str, list[str]],
) -> ChainAtoms:
    """Extract ChainAtoms for an RC_chain lumped element.

    Uses the wall_chains metadata from the atomic_model to distinguish
    interior R nodes from Rse/Rsi surface resistances.
    """
    wall_chains: dict[str, dict] = atomic_model.get("wall_chains", {})
    nodes = _node_map(atomic_model)

    # Find the chain entry matching this lump's element uuid
    elem_uuid = lump.realizes
    if elem_uuid is None:
        # Fall back: infer from atom ids
        r_atom_ids = [
            aid for aid in lump.atoms
            if nodes.get(aid, {}).get("kind") == "resistance"
        ]
        c_atom_ids = [
            aid for aid in lump.atoms
            if nodes.get(aid, {}).get("kind") == "mass"
        ]
        return ChainAtoms(r_atom_ids=r_atom_ids, c_atom_ids=c_atom_ids)

    # Match via expansion_map atoms vs wall_chains r_ids / mass_ids
    for chain in wall_chains.values():
        r_ids = chain.get("r_ids", [])
        mass_ids = chain.get("mass_ids", [])
        # Check if any of this chain's atoms belong to the element
        all_chain_atoms = r_ids + mass_ids
        if any(aid in expansion_map.get(elem_uuid, []) for aid in all_chain_atoms):
            return ChainAtoms(r_atom_ids=r_ids, c_atom_ids=mass_ids)

    # Fallback: classify by node kind
    r_atom_ids = [aid for aid in lump.atoms if nodes.get(aid, {}).get("kind") == "resistance"]
    c_atom_ids = [aid for aid in lump.atoms if nodes.get(aid, {}).get("kind") == "mass"]
    return ChainAtoms(r_atom_ids=r_atom_ids, c_atom_ids=c_atom_ids)


def get_chain_priors(
    lump: LumpedElement,
    atomic_model: dict,
    expansion_map: dict[str, list[str]],
) -> tuple[float, float]:
    """Return (R_interior_nominal, C_total_nominal) for an RC_chain lump.

    R_interior is the sum of the interior R-node nominals (Rse/Rsi excluded).
    This is what phi_R actually controls: the material resistance split across
    the r_atom_ids in the chain.
    """
    nodes = _node_map(atomic_model)
    ca = chain_atoms_for_lump(lump, atomic_model, expansion_map)
    R_nom = sum(nodes[rid]["R"] for rid in ca.r_atom_ids)
    C_nom = sum(nodes[mid]["C"] for mid in ca.c_atom_ids)
    return R_nom, C_nom


# ---------------------------------------------------------------------------
# Small helper missing from lumps.py (single-atom series)
# ---------------------------------------------------------------------------

def compose_series_sum_single(nominal: float, sigma_log: float = 0.5) -> "Prior":
    from thermogram.models import Prior
    return Prior(nominal=nominal, sigma_log=sigma_log)
