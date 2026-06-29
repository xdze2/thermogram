"""
Forward simulation of an assembled System.
Signals are interpolated from arrays; integration via scipy solve_ivp (RK45).
"""

from __future__ import annotations

import numpy as np
from scipy.integrate import solve_ivp

from .assembler import System


def forward_sim(
    system: System,
    signals: dict[str, np.ndarray],
    t_span: tuple[float, float],
    x0: np.ndarray,
    params: dict[str, float],
    dt: float = 3600.0,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Integrate the system ODE forward in time.

    Parameters
    ----------
    system  : assembled System
    signals : {name: array} sampled at uniform dt starting at t_span[0]
    t_span  : (t_start, t_end) in seconds
    x0      : initial state vector (len = len(system.state_names))
    params  : {param_name: value}
    dt      : output time step [s] (also the signal sampling interval)

    Returns
    -------
    t_out   : 1-D array of output times
    x_out   : 2-D array shape (n_states, n_times)
    """
    t0, tf = t_span
    t_eval = np.arange(t0, tf + dt / 2, dt)

    def _interpolate(arr: np.ndarray, t: float) -> float:
        i = (t - t0) / dt
        i0 = int(i)
        i0 = max(0, min(i0, len(arr) - 2))
        frac = i - i0
        return float(arr[i0] * (1 - frac) + arr[i0 + 1] * frac)

    def rhs(t: float, x: np.ndarray) -> np.ndarray:
        sig_t: dict[str, float] = {
            name: _interpolate(arr, t) for name, arr in signals.items()
        }
        if "_T_sol_air" not in sig_t and "T_ext" in sig_t:
            # DEFERRED (Step 0): heavy-wall sol-air uses T_ext only; SOLAR_OPAQUE budget is
            # owned by HeavyWall but not yet active in the dynamics.
            # Finish with pvlib POA: T_sa = T_ext + alpha * G_poa / h_se.
            sig_t["_T_sol_air"] = sig_t["T_ext"]
        return system.rhs(t, x, sig_t, params)

    sol = solve_ivp(rhs, t_span, x0, method="RK45", t_eval=t_eval, max_step=dt)
    if not sol.success:
        raise RuntimeError(f"ODE integration failed: {sol.message}")

    return sol.t, sol.y
