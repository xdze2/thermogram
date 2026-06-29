"""Step 0 acceptance tests."""

import numpy as np
import pytest

from thnodes import (
    Assembler,
    Channel,
    DirectLoss,
    HeavyWall,
    Layer,
    OuterWall,
    RoomMass,
    SolarGainModule,
    Window,
    forward_sim,
)


# ── shared fixtures ────────────────────────────────────────────────────────────

FLOOR_AREA = 20.0  # m²
N_HOURS = 48
DT = 3600.0        # 1-hour step


def _light_wall():
    return OuterWall(
        area=10.0,
        orientation="S",
        layers=[Layer("insulation_mineral_wool", 0.1)],
    )


def _heavy_wall():
    return OuterWall(
        area=10.0,
        orientation="S",
        layers=[Layer("concrete", 0.2), Layer("insulation_mineral_wool", 0.1)],
    )


def _window():
    return Window(area=4.0, orientation="S", U=1.2, shgc=0.6)


def _constant_signals(n: int, T_ext: float = 20.0, G_sol: float = 0.0) -> dict:
    return {
        "T_ext": np.full(n, T_ext),
        "G_sol": np.full(n, G_sol),
    }


# ── caravan topology ───────────────────────────────────────────────────────────
# RoomMass + DirectLoss + SolarGain, state [T_room]

def _build_caravan():
    win = _window()
    wall = _light_wall()
    asm = Assembler()
    asm.add_module(RoomMass(floor_area=FLOOR_AREA))
    asm.add_module(DirectLoss(), elements=[wall, win])
    asm.add_module(SolarGainModule(), elements=[win])
    return asm.build()


def test_caravan_state_names():
    sys = _build_caravan()
    assert sys.state_names == ["T_room"]


def test_caravan_param_names():
    sys = _build_caravan()
    assert "C_room" in sys.param_names
    assert "H_ve" in sys.param_names
    assert "shgcA" in sys.param_names


def test_caravan_signal_names():
    sys = _build_caravan()
    assert "T_ext" in sys.signal_names
    assert "G_sol" in sys.signal_names


# ── heavy-wall topology ────────────────────────────────────────────────────────
# RoomMass + DirectLoss(windows) + HeavyWall(heavy walls) + SolarGain, state [T_wall, T_room]

def _build_heavy():
    heavy = _heavy_wall()
    win = _window()
    asm = Assembler()
    asm.add_module(RoomMass(floor_area=FLOOR_AREA))
    asm.add_module(DirectLoss(), elements=[win])          # window conduction only
    asm.add_module(HeavyWall(), elements=[heavy])         # heavy wall CONDUCTION+STORAGE+SOLAR_OPAQUE
    asm.add_module(SolarGainModule(), elements=[win])     # window SOLAR_TRANSMISSION
    return asm.build()


def test_heavy_state_names():
    sys = _build_heavy()
    assert sys.state_names == ["T_wall", "T_room"]


def test_heavy_param_names():
    sys = _build_heavy()
    for p in ("C_room", "H_ve", "H_out", "H_in", "C_wall", "shgcA"):
        assert p in sys.param_names, f"missing param {p}"


# ── double-count guard ─────────────────────────────────────────────────────────

def test_double_count_raises():
    """Same element routed to two modules that both claim CONDUCTION must raise."""
    heavy = _heavy_wall()
    asm = Assembler()
    asm.add_module(RoomMass(floor_area=FLOOR_AREA))
    asm.add_module(DirectLoss(), elements=[heavy])   # claims CONDUCTION
    asm.add_module(HeavyWall(), elements=[heavy])    # also claims CONDUCTION → double-count
    with pytest.raises(ValueError, match="[Dd]ouble"):
        asm.build()


# ── forward simulation ─────────────────────────────────────────────────────────

def _prior_mean_params(sys) -> dict:
    import math
    return {p: math.exp(mu) for p, (mu, _) in sys.priors.items()}


def test_caravan_step_response():
    """T_room should rise monotonically after a +10°C step in T_ext."""
    sys = _build_caravan()
    params = _prior_mean_params(sys)

    T_init = 15.0
    sigs = _constant_signals(N_HOURS + 2, T_ext=25.0, G_sol=0.0)
    x0 = np.array([T_init])

    t, x = forward_sim(sys, sigs, (0, N_HOURS * DT), x0, params, dt=DT)
    T_room = x[0]

    assert T_room[0] == pytest.approx(T_init, abs=0.1)
    assert T_room[-1] > T_room[0], "T_room should rise toward T_ext"
    assert np.all(np.diff(T_room) >= -0.01), "Step response should be monotone"


def test_heavy_lags_caravan():
    """
    Heavy model T_room should lag the caravan (slower rise) under the same T_ext step.
    At intermediate time (12 h), caravan should be warmer.
    """
    sigs = _constant_signals(N_HOURS + 2, T_ext=25.0, G_sol=0.0)
    x0_c = np.array([15.0])
    x0_h = np.array([15.0, 15.0])  # T_wall, T_room

    sys_c = _build_caravan()
    sys_h = _build_heavy()

    _, x_c = forward_sim(sys_c, sigs, (0, N_HOURS * DT), x0_c, _prior_mean_params(sys_c), dt=DT)
    _, x_h = forward_sim(sys_h, sigs, (0, N_HOURS * DT), x0_h, _prior_mean_params(sys_h), dt=DT)

    T_room_c = x_c[0]
    T_room_h = x_h[-1]  # T_room is last state

    mid = N_HOURS // 4  # 12 h
    assert T_room_c[mid] > T_room_h[mid], (
        f"Caravan should be warmer at t={mid}h: caravan={T_room_c[mid]:.2f}, "
        f"heavy={T_room_h[mid]:.2f}"
    )
