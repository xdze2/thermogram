"""
Named topology modules. Each wraps one flux form and declares:
  - params, signals, private_states, owns
  - derive_priors(cells) -> {param: (mu_log, sigma_log)}
  - flux_room / state_ode  (delegated to the form)

Canonical catalogue (Step 0 minimum): RoomMass, DirectLoss, SolarGainModule, HeavyWall.

Boundary-signal parametrisation (D2):
  DirectLoss, SolarGainModule, and HeavyWall each accept the boundary signal name as a
  constructor argument (T_bnd_signal / G_signal / T_bnd_signal respectively).  The defaults
  reproduce the original hardcoded values ("T_ext" / "G_sol" / "T_ext") so all existing
  callers and tests remain unchanged.  The ``signal`` attribute on each instance records the
  boundary signal name for use by the grouping rule (``ModuleType[Signal]`` notation in
  spec 15 / I8).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .channels import Budget, Channel
from .forms import Conductance, DelayedConductance, SolarGain
from .elements import Rse, Rsi

Params = dict[str, float]
Signals = dict[str, Any]
States = dict[str, float]

_SIGMA_LOG = math.log(1.6)  # ±60% log-normal uncertainty


@dataclass
class TopologyModule:
    name: str
    params: list[str]
    signals: list[str]
    private_states: list[str]
    owns: list[Channel]
    # boundary signal name for ModuleType[Signal] identification (D2).
    # None for modules that have no external boundary signal (e.g. RoomMass).
    signal: str | None = field(default=None, repr=False)
    _form: Any = field(repr=False, default=None)

    def derive_priors(self, cells: dict) -> dict[str, tuple[float, float]]:
        raise NotImplementedError

    def flux_room(self, params: Params, signals: Signals, states: States) -> float:
        return self._form.flux_room(params, signals, states)

    def state_ode(self, params: Params, signals: Signals, states: States) -> dict[str, float]:
        return self._form.state_ode(params, signals, states)


class RoomMass(TopologyModule):
    """
    The room node itself.  Pure topology: owns T_room and C_room but carries no
    physical descriptors.  Its C_room prior is derived by spending the STORAGE
    budget of the room's IndoorMass element, which the assembler auto-routes here.

    No geometry, no floor_area, no heuristic — per spec I4 ("modules spend budgets,
    they never re-invent them").
    """

    def __init__(self):
        super().__init__(
            name="RoomMass",
            params=["C_room"],
            signals=[],
            private_states=[],
            owns=[],
        )

    def derive_priors(self, cells: dict) -> dict[str, tuple[float, float]]:
        """
        Set C_room prior from the STORAGE budget supplied by the assembler.

        ``cells`` is a dict keyed by (element_id, Channel) with Budget values.
        The assembler injects the IndoorMass STORAGE budget here via auto-pairing.
        If no STORAGE budget is found (assembler-level error), fall back to a
        conservative 50 kJ/K so downstream code stays numerically safe.
        """
        from .channels import Channel  # local import avoids circular at module level

        C_storage: float | None = None
        for (_, ch), budget in cells.items():
            if ch is Channel.STORAGE and budget.C is not None:
                C_storage = budget.C
                break

        if C_storage is None or C_storage <= 0.0:
            # Guard: should not happen when an IndoorMass element is present.
            C_storage = 50_000.0  # 50 kJ/K conservative fallback

        return {"C_room": (math.log(C_storage), _SIGMA_LOG)}

    def flux_room(self, params, signals, states) -> float:
        return 0.0

    def state_ode(self, params, signals, states) -> dict[str, float]:
        return {}


class DirectLoss(TopologyModule):
    """
    Lumped memoryless conduction to a boundary temperature signal.

    By default the boundary is T_ext (the exterior), reproducing the original
    single-boundary behaviour.  Pass ``T_bnd_signal`` to mint a distinct module
    for a different boundary (e.g. DirectLoss("T_kitchen") for partitions, or
    DirectLoss("T_ground") for a ground floor).

    The ``signal`` attribute records the boundary signal name so the grouping
    rule can identify the module as DirectLoss[T_bnd_signal].

    Parameter naming
    ~~~~~~~~~~~~~~~~
    When T_bnd_signal is "T_ext" (the default) the param is named "H_ve" — the
    existing name, preserving backward compatibility with all callers, tests, and
    the ODE signal dict.  When a non-default signal is used the param is named
    "H_ve_<signal>" (e.g. "H_ve_T_kitchen") so that two DirectLoss modules in
    the same assembly do not share a param name and produce distinct priors.
    """

    def __init__(self, T_bnd_signal: str = "T_ext"):
        # Param name: legacy "H_ve" for the default signal; qualified otherwise.
        param_name = "H_ve" if T_bnd_signal == "T_ext" else f"H_ve_{T_bnd_signal}"
        form = Conductance(H_param=param_name, T_bnd_signal=T_bnd_signal)
        super().__init__(
            name="DirectLoss",
            params=[param_name],
            signals=[T_bnd_signal],
            private_states=[],
            owns=[Channel.CONDUCTION],
            signal=T_bnd_signal,
            _form=form,
        )
        self._param_name = param_name

    def derive_priors(self, cells: dict) -> dict[str, tuple[float, float]]:
        UA_total = sum(
            b.UA for b in cells.values() if b.UA is not None
        )
        return {self._param_name: (math.log(max(UA_total, 1e-3)), _SIGMA_LOG)}


class SolarGainModule(TopologyModule):
    """
    Solar transmission through windows into T_room.

    By default driven by G_sol (the original single-orientation signal).  Pass
    ``G_signal`` to create a per-orientation instance, e.g.
    SolarGainModule("G_sol_S"), SolarGainModule("G_sol_W").

    The ``signal`` attribute records the irradiance signal name for
    SolarGain[G_signal] identification.

    Parameter naming
    ~~~~~~~~~~~~~~~~
    When G_signal is "G_sol" (the default) the param is named "shgcA" —
    preserving backward compatibility.  For a non-default signal the param is
    named "shgcA_<signal>" (e.g. "shgcA_G_sol_S") so that two SolarGainModule
    instances in the same assembly produce distinct priors and ODE params.
    """

    def __init__(self, G_signal: str = "G_sol"):
        param_name = "shgcA" if G_signal == "G_sol" else f"shgcA_{G_signal}"
        form = SolarGain(aA_param=param_name, G_signal=G_signal)
        super().__init__(
            name="SolarGain",
            params=[param_name],
            signals=[G_signal],
            private_states=[],
            owns=[Channel.SOLAR_TRANSMISSION],
            signal=G_signal,
            _form=form,
        )
        self._param_name = param_name

    def derive_priors(self, cells: dict) -> dict[str, tuple[float, float]]:
        shgcA_total = sum(
            b.shgcA for b in cells.values() if b.shgcA is not None
        )
        return {self._param_name: (math.log(max(shgcA_total, 1e-6)), _SIGMA_LOG)}


class HeavyWall(TopologyModule):
    """
    R-C-R branch for a heavy envelope wall.
    Splits U·A into H_out / H_in by Rse/Rsi ratio around C_wall.
    Private state T_wall; boundary: sol-air (T_ext + absorbed solar).
    Owns CONDUCTION + STORAGE + SOLAR_OPAQUE of heavy exterior walls.

    ``T_bnd_signal`` is the exterior temperature signal name (default "T_ext").
    In all current scenarios heavy walls couple only to the exterior, so the
    default is always used; the parameter exists for API symmetry and future
    sol-air extension.  The ``signal`` attribute records it for
    HeavyWall[T_bnd_signal] identification.
    """

    def __init__(self, T_bnd_signal: str = "T_ext"):
        # DEFERRED: sol-air uses _T_sol_air synthetic signal (simulate.py builds it).
        # The T_bnd_signal here is the *exterior temperature* the sol-air formula
        # wraps around; the form still points to the synthetic _T_sol_air name.
        form = DelayedConductance(
            node_name="T_wall",
            H_out_param="H_out",
            H_in_param="H_in",
            C_param="C_wall",
            T_bnd_signal="_T_sol_air",  # synthetic signal built by assembler / simulate.py
        )
        super().__init__(
            name="HeavyWall",
            params=["H_out", "H_in", "C_wall"],
            signals=[T_bnd_signal, "G_sol"],
            private_states=["T_wall"],
            owns=[Channel.CONDUCTION, Channel.STORAGE, Channel.SOLAR_OPAQUE],
            signal=T_bnd_signal,
            _form=form,
        )

    def derive_priors(self, cells: dict) -> dict[str, tuple[float, float]]:
        UA_total = sum(b.UA for b in cells.values() if b.UA is not None)
        C_total = sum(b.C for b in cells.values() if b.C is not None)
        alphaA_total = sum(b.alphaA for b in cells.values() if b.alphaA is not None)

        # Split U·A into H_out / H_in by surface-resistance ratio around C_wall
        # R_total = Rse + R_layers + Rsi;  H_out ≈ UA * R_total / Rse,  H_in ≈ UA * R_total / Rsi
        # Approximate: H_out / H_in ≈ Rsi / Rse
        ratio = Rsi / Rse  # ~3.25 → H_out < H_in
        H_out_nom = UA_total * (1.0 + ratio) / ratio   # = UA * (Rse + Rsi) / Rse  (approx)
        H_in_nom = UA_total * (1.0 + ratio)             # = UA * (Rse + Rsi) / Rsi  (approx)

        priors = {
            "H_out": (math.log(max(H_out_nom, 1e-3)), _SIGMA_LOG),
            "H_in": (math.log(max(H_in_nom, 1e-3)), _SIGMA_LOG),
            "C_wall": (math.log(max(C_total, 1e3)), _SIGMA_LOG),
        }
        return priors
