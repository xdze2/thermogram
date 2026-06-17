"""
2R2C thermal state-space model for a single room zone.

State vector:  x = [T_wall, T_room]
Inputs:        u = [T_sa, T_ext, Q_room]
Observation:   y = T_room  (x[1])

Continuous-time energy balances:

  C_wall · dT_wall/dt = H_env · (T_sa   - T_wall) - H_int · (T_wall - T_room)
  C_room · dT_room/dt = H_int · (T_wall - T_room) - H_ve  · (T_room - T_ext) + Q_room

where:
  T_sa   = T_ext + α_eff · G_opaque / h_ext   (sol-air temperature)
  Q_room = Q_sol_win + Q_int                   (direct gains into room air)
  H_int  = fixed from ISO 6946 (not a free parameter)

Free parameters for identification: H_env, H_ve, C_wall, C_room, α_eff
"""

from __future__ import annotations

import numpy as np
from scipy.signal import cont2discrete

from .api_models import EnvelopeElement, ElementType, Room
from .iso6946 import surface_resistances, layer_resistance, element_u_value


# Outer surface heat transfer coefficient [W/(m²·K)] — ISO 6946 Table B.1
# R_so = 0.04 m²K/W  →  h_ext = 25 W/(m²K)
H_EXT = 25.0


def opaque_elements(room: Room) -> list[EnvelopeElement]:
    return [e for e in room.elements if e.type != ElementType.window]


def window_elements(room: Room) -> list[EnvelopeElement]:
    return [e for e in room.elements if e.type == ElementType.window]


def h_env_opaque(room: Room) -> float:
    """H_env [W/K] — envelope conduction through opaque elements only."""
    return sum(element_u_value(e) * e.area_m2 for e in opaque_elements(room))


def h_win(room: Room) -> float:
    """H_win [W/K] — direct heat loss through windows (T_ext → T_room path)."""
    return sum(element_u_value(e) * e.area_m2 for e in window_elements(room))


def h_int_from_room(room: Room) -> float:
    """
    H_int [W/K] — inner-surface + layer conductance for opaque elements.

    For each opaque element: H_int_elem = A / (R_si + R_layers)
    This is the conductance from C_wall node to C_room node.
    Fixed from ISO 6946 physics — not a free parameter.
    """
    total = 0.0
    for elem in opaque_elements(room):
        if elem.u_value_override is not None:
            # With override we don't have layer breakdown; approximate from U and R_so
            rsi, rso = surface_resistances(elem)
            r_inner = 1.0 / elem.u_value_override - rso
            r_inner = max(r_inner, rsi)  # at least R_si
        else:
            rsi, _ = surface_resistances(elem)
            r_layers = sum(layer_resistance(l) for l in elem.layers)
            r_inner = rsi + r_layers
        total += elem.area_m2 / r_inner
    return total


def build_state_space(
    H_env: float,
    H_ve: float,
    C_wall: float,
    C_room: float,
    H_int: float,
    H_win: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Build continuous-time A, B matrices for the 2R2C system.

    State:  x = [T_wall, T_room]
    Input:  u = [T_sa, T_ext, Q_room]

    Returns (A, B) as numpy arrays.
    """
    A = np.array([
        [-(H_env + H_int) / C_wall,          H_int / C_wall         ],
        [  H_int           / C_room,  -(H_int + H_ve + H_win) / C_room],
    ])

    B = np.array([
        [H_env / C_wall,    0.0,          0.0        ],
        [0.0,               (H_ve + H_win) / C_room,  1.0 / C_room],
    ])

    return A, B


def discretize(
    A: np.ndarray,
    B: np.ndarray,
    dt: float,
) -> tuple[np.ndarray, np.ndarray]:
    """ZOH discretisation via scipy. Returns (A_d, B_d)."""
    C = np.eye(2)          # observe both states (we select T_room in forward_sim)
    D = np.zeros((2, 3))
    A_d, B_d, _, _, _ = cont2discrete((A, B, C, D), dt, method="zoh")
    return A_d, B_d


def forward_sim_full(
    A_d: np.ndarray,
    B_d: np.ndarray,
    T_sa: np.ndarray,
    T_ext: np.ndarray,
    Q_room: np.ndarray,
    x0: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Like forward_sim but returns (T_wall_pred, T_room_pred)."""
    N = len(T_sa)
    if x0 is None:
        x0 = np.array([T_ext[0], T_ext[0]])
    x = x0.copy()
    T_wall_pred = np.empty(N)
    T_room_pred = np.empty(N)
    for k in range(N):
        u = np.array([T_sa[k], T_ext[k], Q_room[k]])
        T_wall_pred[k] = x[0]
        T_room_pred[k] = x[1]
        x = A_d @ x + B_d @ u
    return T_wall_pred, T_room_pred


def forward_sim(
    A_d: np.ndarray,
    B_d: np.ndarray,
    T_sa: np.ndarray,
    T_ext: np.ndarray,
    Q_room: np.ndarray,
    x0: np.ndarray | None = None,
) -> np.ndarray:
    """
    Step the discrete-time 2R2C model over N timesteps.

    Parameters
    ----------
    A_d, B_d : discretised system matrices
    T_sa     : (N,) sol-air temperature [°C]
    T_ext    : (N,) outdoor temperature [°C]
    Q_room   : (N,) direct gains into room air [W]  (Q_sol_win + Q_int)
    x0       : initial state [T_wall_0, T_room_0]; defaults to T_ext[0] for both

    Returns
    -------
    T_room_pred : (N,) predicted indoor temperature [°C]
    """
    N = len(T_sa)
    if x0 is None:
        x0 = np.array([T_ext[0], T_ext[0]])

    x = x0.copy()
    T_room_pred = np.empty(N)

    for k in range(N):
        u = np.array([T_sa[k], T_ext[k], Q_room[k]])
        T_room_pred[k] = x[1]
        x = A_d @ x + B_d @ u

    return T_room_pred


def sol_air_temperature(
    T_ext: np.ndarray,
    G_opaque: np.ndarray,
    alpha_eff: float,
    h_ext: float = H_EXT,
) -> np.ndarray:
    """
    T_sa = T_ext + α_eff · G_opaque / h_ext

    G_opaque: area-averaged irradiance on opaque surfaces [W/m²]
    Uses a single scalar α_eff and scalar h_ext (ISO 6946 outer surface).
    """
    return T_ext + alpha_eff * G_opaque / h_ext
