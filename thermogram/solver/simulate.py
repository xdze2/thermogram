"""Forward simulation for thermogram.

Two solvers:
  simulate_ivp  — scipy solve_ivp BDF, good for stiff systems and exploration
  simulate_zoh  — matrix-exponential ZOH, exact for piecewise-constant inputs; fast for optimisation
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from .assemble import AssembledSystem


@dataclass
class SimResult:
    t: np.ndarray                   # Unix timestamps [s], shape (n_steps,)
    temps: dict[str, np.ndarray]    # mass_id → temperature array [°C]

    # solver metadata
    solver: str                     # 'ivp_bdf' | 'zoh' | 'mock'
    elapsed_s: float                # wall-clock seconds
    n_steps: int | None             # integrator steps (IVP only)
    n_rhs_evals: int | None         # RHS function evaluations (IVP only)
    success: bool
    message: str


def simulate_ivp(
    system: AssembledSystem,
    inputs: dict[str, tuple[np.ndarray, np.ndarray]],
    start: str,
    end: str,
    dt_minutes: int = 15,
    y0: np.ndarray | None = None,
) -> SimResult:
    """Solve dx/dt = A x + B_boundary u_b(t) + B_source u_s(t) with BDF.

    Parameters
    ----------
    system:
        Assembled state-space system from assemble().
    inputs:
        {node_id: (t_sec, values)} for every boundary and source node.
        t_sec must be monotonically increasing Unix timestamps [s].
    start, end:
        ISO-8601 date strings defining the simulation window.
    dt_minutes:
        Output resolution in minutes (uniform t_eval grid).
    y0:
        Initial temperatures [°C] for each mass node.  If None, all masses
        start at the first value of the first boundary signal (or 20 °C if
        no boundary is present).

    Returns
    -------
    SimResult with solver='ivp_bdf'.
    """
    from scipy.integrate import solve_ivp
    from scipy.interpolate import interp1d
    import datetime

    t0 = datetime.datetime.fromisoformat(start).timestamp()
    t1 = datetime.datetime.fromisoformat(end).timestamp()
    dt = dt_minutes * 60.0
    t_eval = np.arange(t0, t1, dt)

    # Build interpolators for each input signal (zero-order hold at boundaries)
    interp: dict[str, interp1d] = {}
    for node_id, (t_sig, vals) in inputs.items():
        interp[node_id] = interp1d(
            t_sig, vals,
            kind="previous",       # ZOH between samples
            bounds_error=False,
            fill_value=(vals[0], vals[-1]),  # clamp outside range
        )

    # Map node_ids to column indices
    b_ids = system.boundary_ids
    s_ids = system.source_ids
    A = system.A
    B_b = system.B_boundary
    B_s = system.B_source

    def rhs(t: float, x: np.ndarray) -> np.ndarray:
        u_b = np.array([interp[nid](t) for nid in b_ids]) if b_ids else np.zeros(0)
        u_s = np.array([interp[nid](t) for nid in s_ids]) if s_ids else np.zeros(0)
        return A @ x + B_b @ u_b + B_s @ u_s

    # Initial condition
    if y0 is None:
        if b_ids:
            T_init = float(interp[b_ids[0]](t0))
        else:
            T_init = 20.0
        y0 = np.full(len(system.mass_ids), T_init)

    t_start = time.perf_counter()
    sol = solve_ivp(
        rhs,
        t_span=(t0, t1),
        y0=y0,
        method="BDF",
        t_eval=t_eval,
        dense_output=False,
        rtol=1e-4,
        atol=1e-3,
    )
    elapsed = time.perf_counter() - t_start

    temps = {
        mass_id: sol.y[i]
        for i, mass_id in enumerate(system.mass_ids)
    }

    return SimResult(
        t=sol.t,
        temps=temps,
        solver="ivp_bdf",
        elapsed_s=elapsed,
        n_steps=sol.t.size,
        n_rhs_evals=sol.nfev,
        success=sol.success,
        message=sol.message,
    )


def simulate_zoh(
    system: AssembledSystem,
    inputs: dict[str, tuple[np.ndarray, np.ndarray]],
    start: str,
    end: str,
    dt_minutes: int = 15,
    y0: np.ndarray | None = None,
) -> SimResult:
    """Solve dx/dt = A x + B u(t) with zero-order-hold matrix exponential.

    Discretises the continuous system once via scipy.signal.cont2discrete
    (method='zoh'), then steps forward with scipy.signal.dlsim.  Exact for
    piecewise-constant inputs on a uniform grid; O(n³) once, O(n²) per step.

    Parameters
    ----------
    system:
        Assembled state-space system from assemble().
    inputs:
        {node_id: (t_sec, values)} for every boundary and source node.
    start, end:
        ISO-8601 date strings defining the simulation window.
    dt_minutes:
        Time step in minutes (uniform grid used for both discretisation and output).
    y0:
        Initial temperatures [°C].  Defaults to first boundary value (or 20 °C).

    Returns
    -------
    SimResult with solver='zoh'.
    """
    from scipy.signal import cont2discrete, dlsim
    from scipy.interpolate import interp1d
    import datetime

    t0 = datetime.datetime.fromisoformat(start).timestamp()
    t1 = datetime.datetime.fromisoformat(end).timestamp()
    dt = dt_minutes * 60.0
    t_eval = np.arange(t0, t1, dt)
    n_steps = len(t_eval)

    b_ids = system.boundary_ids
    s_ids = system.source_ids
    n_b = len(b_ids)
    n_s = len(s_ids)
    n_u = n_b + n_s
    n_x = len(system.mass_ids)

    # Full B matrix: [B_boundary | B_source], shape (n_x, n_u)
    B_full = np.hstack([
        system.B_boundary if n_b > 0 else np.zeros((n_x, 0)),
        system.B_source   if n_s > 0 else np.zeros((n_x, 0)),
    ])

    # Discretise once (ZOH)
    C_eye = np.eye(n_x)
    D_zero = np.zeros((n_x, n_u))
    Ad, Bd, _, _, _ = cont2discrete((system.A, B_full, C_eye, D_zero), dt, method="zoh")

    # Build input matrix u: shape (n_steps, n_u)
    all_ids = b_ids + s_ids
    interp_fns: list[interp1d] = []
    for node_id in all_ids:
        t_sig, vals = inputs[node_id]
        interp_fns.append(interp1d(
            t_sig, vals,
            kind="previous",
            bounds_error=False,
            fill_value=(vals[0], vals[-1]),
        ))
    u = np.column_stack([fn(t_eval) for fn in interp_fns]) if n_u > 0 else np.zeros((n_steps, 0))

    # Initial condition
    if y0 is None:
        if b_ids:
            T_init = float(interp_fns[0](t0))
        else:
            T_init = 20.0
        y0 = np.full(n_x, T_init)

    t_start = time.perf_counter()
    # dlsim returns (t_out, y_out, x_out); we want x_out (state trajectory)
    _, _, x_out = dlsim((Ad, Bd, C_eye, D_zero, dt), u, x0=y0)
    elapsed = time.perf_counter() - t_start

    # x_out shape: (n_steps, n_x)
    temps = {
        mass_id: x_out[:, i]
        for i, mass_id in enumerate(system.mass_ids)
    }

    return SimResult(
        t=t_eval,
        temps=temps,
        solver="zoh",
        elapsed_s=elapsed,
        n_steps=n_steps,
        n_rhs_evals=None,
        success=True,
        message="ok",
    )

