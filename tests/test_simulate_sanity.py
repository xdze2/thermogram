"""
Stage 3 — forward-simulation tests over the assembled module graph.

Two kinds of check:

  1. Correctness anchor: for the current topology the assembled (A, B) must equal the
     legacy `state_space.build_state_space` lumped 2R2C. This replaces the
     eyeball-the-plots check with an exact equivalence to the known-good engine.

  2. Physical-ordering sanity: caravan (all-light) tracks T_ext fastest; passive is the
     most damped; passive's dominant time constant exceeds the caravan's. These are the
     dynamics assertions static priors can't make.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from thermal.api_models import Room
from thermal.assembler import assemble
from thermal.priors import build_priors
from thermal.simulate import assemble_system, integrate, sample_params, AGG_WALL_NODE
from thermal.state_space import build_state_space, h_int_from_room
from thermal import modules as M

FIXTURES = Path(__file__).parent / "fixtures"


def load_room(name: str) -> Room:
    return Room(**json.loads((FIXTURES / f"{name}.json").read_text()))


def _mu_params(prior) -> dict:
    return {
        "H_env": prior.H_env.mu, "H_ve": prior.H_ve.mu,
        "C_wall": prior.C_wall.mu, "C_room": prior.C_room.mu,
    }


# ---------------------------------------------------------------------------
# 1. Correctness anchor — assembled graph == build_state_space 2R2C
# ---------------------------------------------------------------------------

def _heavy_room() -> Room:
    """Heavy walls + a window → a clean 2R2C with all of H_env through the mass node."""
    return Room(
        floor_area_m2=20, height_m=2.5, latitude=45, longitude=5, ach=0.5,
        elements=[
            {"type": "wall", "name": "N", "uid": "n0000000", "orientation": "N",
             "area_m2": 12, "layers": [{"material_key": "brick_common", "thickness_m": 0.20}]},
            {"type": "wall", "name": "S", "uid": "s0000000", "orientation": "S",
             "area_m2": 12, "layers": [{"material_key": "brick_common", "thickness_m": 0.20}]},
            {"type": "window", "name": "W", "uid": "w0000000", "orientation": "S",
             "area_m2": 2, "u_value_override": 1.4, "shgc": 0.6},
        ],
    )


def _reorder_to_wall_room(sys):
    """Return (A, B) reordered to legacy [T_wall, T_room] state, [T_sa, T_ext, Q_room]."""
    ri = sys.room_index
    wi = 1 - ri
    P = np.zeros((2, 2))
    P[0, wi] = 1.0  # row 0 = wall
    P[1, ri] = 1.0  # row 1 = room
    A = P @ sys.A @ P.T
    sig = {k: i for i, k in enumerate(sys.signal_keys)}
    B = np.zeros((2, 3))
    for new_col, name in enumerate(("T_sa", "T_ext", "Q_room")):
        if name in sig:
            B[:, new_col] = (P @ sys.B[:, [sig[name]]]).ravel()
    return A, B


def test_assembled_system_equals_2r2c():
    room = _heavy_room()
    prior = build_priors(room)
    sys = assemble_system(room, _mu_params(prior), aggregate=True)

    assert set(sys.node_keys) == {M.ROOM_NODE, AGG_WALL_NODE}
    A_mine, B_mine = _reorder_to_wall_room(sys)
    A_ref, B_ref = build_state_space(
        prior.H_env.mu, prior.H_ve.mu, prior.C_wall.mu, prior.C_room.mu,
        h_int_from_room(room), H_win=0.0,
    )
    assert np.allclose(A_mine, A_ref)
    assert np.allclose(B_mine, B_ref)


def test_aggregate_collapses_heavy_walls_to_one_node():
    """House has 4 heavy walls + heavy floor; aggregate → one shared T_wall node."""
    room = load_room("house")
    prior = build_priors(room)
    sys_agg = assemble_system(room, _mu_params(prior), aggregate=True)
    sys_per = assemble_system(room, _mu_params(prior), aggregate=False)

    assert sys_agg.node_keys == [M.ROOM_NODE, AGG_WALL_NODE]
    # Per-element: one mass node per heavy opaque element (4 walls + roof + floor are
    # all heavy in this fixture) + the room node.
    n_heavy = sum(1 for m in assemble(room) if isinstance(m, M.HeavyWall) and m.is_heavy)
    assert n_heavy == 6
    assert len(sys_per.node_keys) == 1 + n_heavy


def test_caravan_is_single_node_no_heavy_mass():
    """All-light caravan: no mass node, just T_room (a 1R1C reduction)."""
    room = load_room("caravan")
    prior = build_priors(room)
    sys = assemble_system(room, _mu_params(prior), aggregate=True)
    assert sys.node_keys == [M.ROOM_NODE]


# ---------------------------------------------------------------------------
# 2. Physical-ordering sanity
# ---------------------------------------------------------------------------

def _dominant_tau(sys) -> float:
    """Slowest time constant of the system [s] = -1 / max(Re eigenvalue)."""
    eig = np.linalg.eigvals(sys.A)
    slowest = max(e.real for e in eig)  # closest to zero (least negative)
    return -1.0 / slowest


def _step_response_room(room, prior, dt=3600.0, n=24 * 30):
    """Drive a unit step in T_ext (cold→warm) from equilibrium; return T_room track."""
    sys = assemble_system(room, _mu_params(prior), aggregate=True)
    T_ext = np.concatenate([np.zeros(24), np.full(n - 24, 10.0)])
    signals = {"T_ext": T_ext, "T_sa": T_ext.copy(), "Q_room": np.zeros(n)}
    x0 = np.zeros(len(sys.node_keys))  # start at the cold equilibrium (0 °C)
    traj = integrate(sys, signals, dt, x0=x0)
    return traj[:, sys.room_index]


def test_caravan_tracks_text_fastest():
    """Lightest building reaches the new ambient soonest after a T_ext step."""
    def settle_fraction(case):
        room = load_room(case)
        T_room = _step_response_room(room, build_priors(room))
        # fraction of the 10 °C step reached one day after the step
        return T_room[24 + 24] / 10.0

    f_caravan = settle_fraction("caravan")
    f_house = settle_fraction("house")
    f_passive = settle_fraction("passive")
    assert f_caravan > f_house
    assert f_caravan > f_passive


def test_passive_most_damped_largest_tau():
    """Passive house has the longest dominant time constant; caravan the shortest."""
    taus = {}
    for case in ("caravan", "house", "passive"):
        room = load_room(case)
        taus[case] = _dominant_tau(assemble_system(room, _mu_params(build_priors(room)),
                                                    aggregate=True))
    assert taus["passive"] > taus["caravan"]
    assert taus["house"] > taus["caravan"]


def test_tau_in_plausible_range():
    """Building time constants should be hours-to-weeks, never sub-minute or absurd."""
    for case in ("house", "passive"):
        tau = _dominant_tau(assemble_system(load_room(case),
                                            _mu_params(build_priors(load_room(case))),
                                            aggregate=True))
        hours = tau / 3600.0
        assert 1.0 < hours < 24 * 30, f"{case}: τ={hours:.1f} h out of range"


# ---------------------------------------------------------------------------
# Monte-Carlo plumbing
# ---------------------------------------------------------------------------

def test_sample_params_positive_and_seeded():
    prior = build_priors(load_room("house"))
    rng = np.random.default_rng(0)
    s1 = sample_params(prior, rng)
    assert all(v > 0 for k, v in s1.items() if k in ("H_env", "H_ve", "C_room"))
    assert s1["C_wall"] >= 0
    # determinism for a fixed seed
    assert sample_params(prior, np.random.default_rng(0)) == \
           sample_params(prior, np.random.default_rng(0))
