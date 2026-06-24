"""
Forward Monte-Carlo simulation over the assembled module graph (roadmap Stage 3).

Builds the continuous-time linear system `dx/dt = A x + B u` by collecting each
module's `Dynamics` contribution (nodes, inter-node couplings, source couplings,
source fluxes) into a node graph, then samples the parameter priors and integrates an
ensemble of trajectories.

For the current topology this assembles the same 2R2C system as
`state_space.build_state_space` — that equivalence is the correctness anchor (see
`tests/test_simulate_sanity.py`), replacing the eyeball-the-plots check.

Granularity (physics_model.md §4): heavy walls may keep per-element mass nodes
(`aggregate=False`, default) or collapse into one shared `T_wall` node
(`aggregate=True`), which recovers the classic 2R2C. Node merging sums capacitances and
conductances of same-key nodes, so the aggregated graph carries the total
`C_wall`/`H_env`/`H_int`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import cont2discrete

from .api_models import Room, RCModelOut
from .assembler import assemble
from .state_space import h_int_from_room
from . import modules as M

AGG_WALL_NODE = "T_wall"


# ---------------------------------------------------------------------------
# Parameter sampling
# ---------------------------------------------------------------------------

def _scalar_priors(prior: RCModelOut) -> dict[str, tuple[float, float]]:
    """(mu, sigma) for the sampled scalars. C_wall/H_env are split per heavy wall."""
    return {
        "H_env": (prior.H_env.mu, prior.H_env.sigma),
        "H_ve": (prior.H_ve.mu, prior.H_ve.sigma),
        "C_wall": (prior.C_wall.mu, prior.C_wall.sigma),
        "C_room": (prior.C_room.mu, prior.C_room.sigma),
    }


def sample_params(prior: RCModelOut, rng: np.random.Generator) -> dict[str, float]:
    """One draw of the 5 priors (Gaussian, clipped positive), plus fixed H_int.

    H_int is not a free prior — it is fixed from ISO 6946 and carried so the wall→room
    coupling matches build_state_space.
    """
    out: dict[str, float] = {}
    for name, (mu, sigma) in _scalar_priors(prior).items():
        val = rng.normal(mu, sigma) if sigma > 0 else mu
        out[name] = max(val, 1e-9) if name in ("H_env", "H_ve", "C_room") else max(val, 0.0)
    return out


# ---------------------------------------------------------------------------
# Graph → A, B
# ---------------------------------------------------------------------------

@dataclass
class AssembledSystem:
    node_keys: list[str]          # state ordering; ROOM_NODE is guaranteed present
    signal_keys: list[str]        # input ordering
    A: np.ndarray                 # (n, n)
    B: np.ndarray                 # (n, m)

    @property
    def room_index(self) -> int:
        return self.node_keys.index(M.ROOM_NODE)


def _ua(m: "M.HeavyWall") -> float:
    from .iso6946 import element_u_value
    return element_u_value(m.element) * m.element.area_m2


def assemble_system(room: Room, params: dict, aggregate: bool = False) -> AssembledSystem:
    """Build (A, B) for one parameter sample by collecting module Dynamics.

    The sampled scalars are split back across the opaque-wall modules by their physical
    share — `H_env`/`H_int` by U·A, `C_wall` by heavy mass — so that when same-key nodes
    merge (aggregate mode) the totals are exactly recovered. This is what makes the
    assembled graph equal build_state_space's lumped 2R2C.
    """
    mods = assemble(room)
    h_int_total = h_int_from_room(room)

    opaque = [m for m in mods if isinstance(m, M.HeavyWall)]
    heavy = [m for m in opaque if m.is_heavy]
    ua_total = sum(_ua(m) for m in opaque)
    c_total = sum(m.budgets[M.STORAGE].value for m in heavy)

    dyn_list: list[M.Dynamics] = []
    for m in mods:
        if isinstance(m, M.HeavyWall) and m.is_heavy:
            frac_c = m.budgets[M.STORAGE].value / c_total if c_total else 0.0
            frac_ua = _ua(m) / ua_total if ua_total else 0.0
            m.node_key = AGG_WALL_NODE if aggregate else f"T_wall_{m.element.uid}"
            dyn_list.append(m.dynamics({
                "C_wall": params["C_wall"] * frac_c,
                "H_env": params["H_env"] * frac_ua,
                "H_int": h_int_total * frac_ua,
            }))
        elif isinstance(m, M.HeavyWall):
            # Light opaque: its U·A share of H_env conducts T_sa→T_room directly.
            frac_ua = _ua(m) / ua_total if ua_total else 0.0
            dyn_list.append(m.dynamics({"H_env": params["H_env"] * frac_ua}))
        else:
            dyn_list.append(m.dynamics({
                "C_room": params["C_room"],
                "H_ve": params["H_ve"],
            }))

    return _graph_to_state_space(dyn_list)


def _graph_to_state_space(dyn_list: list[M.Dynamics]) -> AssembledSystem:
    # Merge nodes by key (sum capacitances).
    cap: dict[str, float] = {}
    for d in dyn_list:
        for n in d.nodes:
            cap[n.key] = cap.get(n.key, 0.0) + n.capacitance

    node_keys = sorted(cap, key=lambda k: (k != M.ROOM_NODE, k))  # T_room first
    idx = {k: i for i, k in enumerate(node_keys)}

    signal_keys: list[str] = []

    def sig_index(name: str) -> int:
        if name not in signal_keys:
            signal_keys.append(name)
        return signal_keys.index(name)

    n = len(node_keys)
    # Build conductance contributions first; size B after signals known.
    A = np.zeros((n, n))
    src_terms: list[tuple[int, str, float]] = []   # (node_i, signal, H)  conductance
    flux_terms: list[tuple[int, str, float]] = []  # (node_i, signal, gain)

    for d in dyn_list:
        for nc in d.node_couplings:
            i, j = idx[nc.a], idx[nc.b]
            A[i, i] -= nc.H
            A[i, j] += nc.H
            A[j, j] -= nc.H
            A[j, i] += nc.H
        for sc in d.source_couplings:
            i = idx[sc.node]
            A[i, i] -= sc.H
            src_terms.append((i, sc.signal, sc.H))
        for sf in d.source_fluxes:
            i = idx[sf.node]
            flux_terms.append((i, sf.signal, sf.gain))

    # Register signals (couplings then fluxes) and normalise A, B by capacitance.
    for _, name, _ in src_terms:
        sig_index(name)
    for _, name, _ in flux_terms:
        sig_index(name)

    m = len(signal_keys)
    B = np.zeros((n, m))
    for i, name, H in src_terms:
        B[i, sig_index(name)] += H
    for i, name, gain in flux_terms:
        B[i, sig_index(name)] += gain

    # Divide each row by its node capacitance (C·dT/dt = ... → dT/dt = .../C).
    for k, i in idx.items():
        c = cap[k]
        A[i, :] /= c
        B[i, :] /= c

    return AssembledSystem(node_keys, signal_keys, A, B)


# ---------------------------------------------------------------------------
# Integration + Monte-Carlo ensemble
# ---------------------------------------------------------------------------

def integrate(sys: AssembledSystem, signals: dict[str, np.ndarray],
              dt: float, x0: np.ndarray | None = None) -> np.ndarray:
    """ZOH-integrate the system. Returns (N, n_nodes) state trajectory.

    `signals` maps each signal key in `sys.signal_keys` to an (N,) array.
    """
    n = len(sys.node_keys)
    m = len(sys.signal_keys)
    N = len(next(iter(signals.values()))) if signals else 0

    C = np.eye(n)
    D = np.zeros((n, m))
    A_d, B_d, _, _, _ = cont2discrete((sys.A, sys.B, C, D), dt, method="zoh")

    U = np.zeros((N, m))
    for j, key in enumerate(sys.signal_keys):
        U[:, j] = signals[key]

    if x0 is None:
        # Start all nodes at the first ambient temperature available.
        t0 = signals.get("T_ext")
        x0 = np.full(n, t0[0] if t0 is not None else 0.0)

    x = x0.astype(float).copy()
    traj = np.empty((N, n))
    for k in range(N):
        traj[k] = x
        x = A_d @ x + B_d @ U[k]
    return traj


def simulate(room: Room, prior: RCModelOut, signals: dict[str, np.ndarray],
             dt: float, n_draws: int, aggregate: bool = True,
             seed: int | None = 0) -> dict:
    """Monte-Carlo forward simulation: sample priors → integrate → ensemble of T_room.

    `signals` must provide every driving signal the modules need: `T_ext`, `T_sa`
    (sol-air, built from T_ext + α·G/h_ext), `Q_room` (transmitted-solar + internal
    gains). Returns the room-node ensemble plus the node ordering of the last system.
    """
    rng = np.random.default_rng(seed)
    N = len(next(iter(signals.values())))
    room_ens = np.empty((n_draws, N))
    last_sys = None
    for d in range(n_draws):
        params = sample_params(prior, rng)
        sys = assemble_system(room, params, aggregate=aggregate)
        traj = integrate(sys, signals, dt)
        room_ens[d] = traj[:, sys.room_index]
        last_sys = sys
    return {"T_room": room_ens, "node_keys": last_sys.node_keys}
