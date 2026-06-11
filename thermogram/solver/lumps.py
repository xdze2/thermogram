"""Lumped model layer — combine rules and phi → atom-values expansion.

A LumpedElement aggregates one or more atomic nodes under a single fit
parameter (or pair of parameters for RC_chain).  The combine rule maps
phi → individual atom values, with weights derived from atom priors so
that phi == prior ⇒ every atom == its own prior nominal.

Five combine rules (matching modeling_pipeline.md):

  series_sum        Req from N atoms in series:
                    R_atom_i = phi * w_i,  w_i = R_nom_i / sum(R_nom)

  parallel_sum      Ceq from N atoms in parallel:
                    C_atom_i = phi * w_i,  w_i = C_nom_i / sum(C_nom)

  parallel_inv_sum  Req from N atoms in parallel:
                    1/R_atom_i = (1/phi) * w_i,
                    w_i = (1/R_nom_i) / sum(1/R_nom)
                    i.e. R_atom_i = phi * sum(1/R_nom) * R_nom_i

  chain             RC_chain(n): phi = (R_total, C_total)
                    R_atom_i = R_total / n_r_atoms
                    C_atom_i = C_total / n_c_atoms

  identity          Boundary / source: atom_value = phi  (single atom)

All functions are pure (no side effects).  The atomic model dict is NOT
mutated; callers must apply the returned atom_values via _apply_atom_values.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from thermogram.models import (
    CombineRule,
    FitMode,
    LumpedElement,
    Posterior,
    Prior,
    View,
)

# ---------------------------------------------------------------------------
# Combine rules: phi_values → {atom_id: value}
# ---------------------------------------------------------------------------

def apply_series_sum(
    phi: float,
    atom_ids: list[str],
    atom_nominals: list[float],
) -> dict[str, float]:
    """Series R atoms: R_atom_i = phi * (nom_i / sum(nom))."""
    total = sum(atom_nominals)
    return {aid: phi * (nom / total) for aid, nom in zip(atom_ids, atom_nominals)}


def apply_parallel_sum(
    phi: float,
    atom_ids: list[str],
    atom_nominals: list[float],
) -> dict[str, float]:
    """Parallel C atoms: C_atom_i = phi * (nom_i / sum(nom))."""
    total = sum(atom_nominals)
    return {aid: phi * (nom / total) for aid, nom in zip(atom_ids, atom_nominals)}


def apply_parallel_inv_sum(
    phi: float,
    atom_ids: list[str],
    atom_nominals: list[float],
) -> dict[str, float]:
    """Parallel R atoms: conductances share proportionally.

    G_total = 1/phi; G_nom_i = 1/R_nom_i; w_i = G_nom_i / sum(G_nom)
    G_atom_i = G_total * w_i  ⇒  R_atom_i = phi / (G_nom_i / sum(G_nom) * phi ... )

    Simpler derivation: R_atom_i = 1 / (w_i / phi) where w_i = G_nom_i / sum(G_nom).
    """
    g_noms = [1.0 / r for r in atom_nominals]
    g_total_nom = sum(g_noms)
    weights = [g / g_total_nom for g in g_noms]  # sum == 1
    return {aid: 1.0 / (w / phi) for aid, w in zip(atom_ids, weights)}


def apply_chain(
    phi_R: float,
    phi_C: float,
    r_atom_ids: list[str],
    c_atom_ids: list[str],
) -> dict[str, float]:
    """RC_chain: distribute R_total and C_total uniformly across chain atoms."""
    n_r = len(r_atom_ids)
    n_c = len(c_atom_ids)
    result: dict[str, float] = {}
    if n_r > 0:
        r_each = phi_R / n_r
        for aid in r_atom_ids:
            result[aid] = r_each
    if n_c > 0:
        c_each = phi_C / n_c
        for aid in c_atom_ids:
            result[aid] = c_each
    return result


def apply_identity(phi: float, atom_id: str) -> dict[str, float]:
    """Identity: atom = phi directly (boundary T or source gain)."""
    return {atom_id: phi}


# ---------------------------------------------------------------------------
# High-level: expand a LumpedElement's phi value(s) to atom values
# ---------------------------------------------------------------------------

@dataclass
class ChainAtoms:
    """Atom id lists for an RC_chain lumped element."""
    r_atom_ids: list[str]   # interior R-node ids (excludes Rse/Rsi)
    c_atom_ids: list[str]   # mass-node ids


def expand_lumped(
    lump: LumpedElement,
    phi: float | tuple[float, float],
    chain_atoms: ChainAtoms | None = None,
    atom_nominals: list[float] | None = None,
) -> dict[str, float]:
    """Expand a LumpedElement's phi to {atom_id: value}.

    Parameters
    ----------
    lump:
        The LumpedElement describing which atoms to expand and how.
    phi:
        Scalar for all rules except RC_chain; tuple (R_total, C_total) for chain.
    chain_atoms:
        Required for RC_chain: lists of R and C atom ids within the chain
        (Rse/Rsi excluded — they are fixed and not patched).
    atom_nominals:
        Nominal atom values for series_sum / parallel_sum / parallel_inv_sum,
        in the same order as lump.atoms.  Not needed for chain / identity.
    """
    rule = lump.combine

    if rule == "identity":
        assert isinstance(phi, (int, float))
        assert len(lump.atoms) == 1
        return apply_identity(float(phi), lump.atoms[0])

    if rule == "chain":
        assert chain_atoms is not None, "chain_atoms required for RC_chain"
        assert isinstance(phi, tuple) and len(phi) == 2
        phi_R, phi_C = float(phi[0]), float(phi[1])
        return apply_chain(phi_R, phi_C, chain_atoms.r_atom_ids, chain_atoms.c_atom_ids)

    assert isinstance(phi, (int, float)), f"scalar phi required for {rule}"
    assert atom_nominals is not None, f"atom_nominals required for {rule}"
    phi_f = float(phi)

    if rule == "series_sum":
        return apply_series_sum(phi_f, lump.atoms, atom_nominals)
    if rule == "parallel_sum":
        return apply_parallel_sum(phi_f, lump.atoms, atom_nominals)
    if rule == "parallel_inv_sum":
        return apply_parallel_inv_sum(phi_f, lump.atoms, atom_nominals)

    raise ValueError(f"Unknown combine rule: {rule!r}")


# ---------------------------------------------------------------------------
# Apply atom values back onto an atomic model dict (returns deep copy)
# ---------------------------------------------------------------------------

# Map from atom kind to the field name in the node dict
_ATOM_FIELD = {
    "mass": "C",
    "resistance": "R",
    "source": "gain",
    "boundary": "T_source",
}


def apply_atom_values(
    atomic_model: dict,
    atom_values: dict[str, float],
) -> dict:
    """Return a deep copy of atomic_model with the given atom values patched in.

    Only touches nodes whose ids appear in atom_values.  Raises ValueError if
    an id is missing from the model.
    """
    m = copy.deepcopy(atomic_model)
    nodes_by_id = {n["id"]: n for n in m["nodes"]}
    for atom_id, value in atom_values.items():
        if atom_id not in nodes_by_id:
            raise ValueError(f"Atom id {atom_id!r} not found in atomic_model")
        node = nodes_by_id[atom_id]
        field_name = _ATOM_FIELD.get(node["kind"])
        if field_name is None:
            raise ValueError(f"Node kind {node['kind']!r} has no patchable field")
        node[field_name] = value
    return m


# ---------------------------------------------------------------------------
# Prior composition helpers
# ---------------------------------------------------------------------------

def compose_series_prior(atom_nominals: list[float], sigma_log: float = 0.5) -> Prior:
    """Prior for a series_sum lump: nominal = sum of atom nominals."""
    return Prior(nominal=sum(atom_nominals), sigma_log=sigma_log)


def compose_parallel_sum_prior(atom_nominals: list[float], sigma_log: float = 0.5) -> Prior:
    """Prior for a parallel_sum (Ceq) lump: nominal = sum of atom nominals."""
    return Prior(nominal=sum(atom_nominals), sigma_log=sigma_log)


def compose_parallel_inv_prior(atom_nominals: list[float], sigma_log: float = 0.5) -> Prior:
    """Prior for a parallel_inv_sum (Req) lump: nominal = 1/sum(1/R_i)."""
    nominal = 1.0 / sum(1.0 / r for r in atom_nominals)
    return Prior(nominal=nominal, sigma_log=sigma_log)


def compose_chain_prior(
    R_wall: float,
    C_wall: float,
    sigma_log: float = 0.5,
) -> tuple[Prior, Prior]:
    """Priors for RC_chain (R_total, C_total)."""
    return (
        Prior(nominal=R_wall, sigma_log=sigma_log),
        Prior(nominal=C_wall, sigma_log=sigma_log),
    )
