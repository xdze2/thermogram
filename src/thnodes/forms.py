"""
The four canonical flux forms. Each exposes:
  flux_room(params, signals, states) -> float
  state_ode(params, signals, states) -> dict[str, float]   (empty if stateless)
"""

from typing import Any

Params = dict[str, float]
Signals = dict[str, Any]   # callable(t) or array; caller resolves to float at time t
States = dict[str, float]


class Conductance:
    """H * (T_bnd - T_room). No private state."""

    def __init__(self, H_param: str, T_bnd_signal: str):
        self.H_param = H_param
        self.T_bnd_signal = T_bnd_signal

    def flux_room(self, params: Params, signals: Signals, states: States) -> float:
        H = params[self.H_param]
        T_bnd = signals[self.T_bnd_signal]
        T_room = states["T_room"]
        return H * (T_bnd - T_room)

    def state_ode(self, params: Params, signals: Signals, states: States) -> dict[str, float]:
        return {}


class SolarGain:
    """aA * G into T_room. No private state."""

    def __init__(self, aA_param: str, G_signal: str):
        self.aA_param = aA_param
        self.G_signal = G_signal

    def flux_room(self, params: Params, signals: Signals, states: States) -> float:
        aA = params[self.aA_param]
        G = signals[self.G_signal]
        return aA * G

    def state_ode(self, params: Params, signals: Signals, states: States) -> dict[str, float]:
        return {}


class DelayedConductance:
    """
    H_in * (T_node - T_room) into T_room.
    Private state T_node with ODE:
      C * dT_node/dt = H_out * (T_bnd - T_node) - H_in * (T_node - T_room)
    """

    def __init__(
        self,
        node_name: str,
        H_out_param: str,
        H_in_param: str,
        C_param: str,
        T_bnd_signal: str,
    ):
        self.node_name = node_name
        self.H_out_param = H_out_param
        self.H_in_param = H_in_param
        self.C_param = C_param
        self.T_bnd_signal = T_bnd_signal

    def flux_room(self, params: Params, signals: Signals, states: States) -> float:
        H_in = params[self.H_in_param]
        T_node = states[self.node_name]
        T_room = states["T_room"]
        return H_in * (T_node - T_room)

    def state_ode(self, params: Params, signals: Signals, states: States) -> dict[str, float]:
        H_out = params[self.H_out_param]
        H_in = params[self.H_in_param]
        C = params[self.C_param]
        T_bnd = signals[self.T_bnd_signal]
        T_node = states[self.node_name]
        T_room = states["T_room"]
        dT_node = (H_out * (T_bnd - T_node) - H_in * (T_node - T_room)) / C
        return {self.node_name: dT_node}


class SourceFlux:
    """Q(t) prescribed heat input. No private state."""

    def __init__(self, Q_signal: str):
        self.Q_signal = Q_signal

    def flux_room(self, params: Params, signals: Signals, states: States) -> float:
        return signals[self.Q_signal]

    def state_ode(self, params: Params, signals: Signals, states: States) -> dict[str, float]:
        return {}
