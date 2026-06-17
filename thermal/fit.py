"""
MAP fit of 2R2C thermal model parameters from observed indoor temperature.

Free parameters (fitted in log-space to enforce positivity):
  theta = [H_env, H_ve, C_wall, C_room, alpha_eff]

Loss function:
  L(theta) = -log_prior(theta) + 0.5 * ||T_room_pred - T_room_obs||² / sigma_obs²

Gaussian priors come from RCModelOut (output of build_priors).
alpha_eff uses a logit-transform instead of log (bounded 0–1).

H_int is fixed from ISO 6946 geometry (not fitted).
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize

from .api_models import RCModelOut
from .state_space import build_state_space, discretize, forward_sim, sol_air_temperature


# Observation noise (assumed, 1-sigma) [°C]
_SIGMA_OBS = 0.5


class FitResult:
    """Posterior MAP estimate for all five RC parameters."""

    def __init__(
        self,
        H_env: float,
        H_ve: float,
        C_wall: float,
        C_room: float,
        alpha_eff: float,
        H_int: float,
        success: bool,
        message: str,
        n_obs: int,
        residual_rmse: float,
        timestamps: list[str] | None = None,
        T_room_pred: list[float] | None = None,
        T_wall_pred: list[float] | None = None,
        T_wall_0: float = 0.0,
        T_room_0: float = 0.0,
    ):
        self.H_env      = H_env
        self.H_ve       = H_ve
        self.C_wall     = C_wall
        self.C_room     = C_room
        self.alpha_eff  = alpha_eff
        self.H_int      = H_int
        self.success    = success
        self.message    = message
        self.n_obs      = n_obs
        self.residual_rmse = residual_rmse
        self.timestamps  = timestamps or []
        self.T_room_pred = T_room_pred or []
        self.T_wall_pred = T_wall_pred or []
        self.T_wall_0    = T_wall_0
        self.T_room_0    = T_room_0

    def to_dict(self) -> dict:
        return {
            "H_env":     self.H_env,
            "H_ve":      self.H_ve,
            "C_wall":    self.C_wall,
            "C_room":    self.C_room,
            "alpha_eff": self.alpha_eff,
            "H_int":     self.H_int,
            "T_wall_0":  self.T_wall_0,
            "T_room_0":  self.T_room_0,
            "success":   self.success,
            "message":   self.message,
            "n_obs":     self.n_obs,
            "residual_rmse": self.residual_rmse,
            "timestamps":  self.timestamps,
            "T_room_pred": self.T_room_pred,
            "T_wall_pred": self.T_wall_pred,
        }


# ---------------------------------------------------------------------------
# Parameter transforms (unconstrained ↔ physical)
# ---------------------------------------------------------------------------

def _to_unconstrained(H_env, H_ve, C_wall, C_room, alpha_eff, T_wall_0, T_room_0) -> np.ndarray:
    """Map physical params to unconstrained space for the optimizer."""
    return np.array([
        np.log(H_env),
        np.log(H_ve),
        np.log(C_wall),
        np.log(C_room),
        np.log(alpha_eff / (1.0 - alpha_eff)),   # logit
        T_wall_0,   # °C — no transform needed
        T_room_0,   # °C — no transform needed
    ])


def _to_physical(p: np.ndarray) -> tuple[float, float, float, float, float, float, float]:
    """Map unconstrained optimizer vector back to physical parameters."""
    H_env     = float(np.exp(p[0]))
    H_ve      = float(np.exp(p[1]))
    C_wall    = float(np.exp(p[2]))
    C_room    = float(np.exp(p[3]))
    alpha_eff = float(1.0 / (1.0 + np.exp(-p[4])))   # sigmoid
    T_wall_0  = float(p[5])
    T_room_0  = float(p[6])
    return H_env, H_ve, C_wall, C_room, alpha_eff, T_wall_0, T_room_0


# ---------------------------------------------------------------------------
# Loss function
# ---------------------------------------------------------------------------

_SIGMA_IC = 3.0   # prior sigma on initial temperatures [°C]


def _neg_log_posterior(
    p: np.ndarray,
    prior: RCModelOut,
    H_int: float,
    H_win: float,
    dt: float,
    G_opaque: np.ndarray,
    T_ext: np.ndarray,
    Q_room: np.ndarray,
    T_obs: np.ndarray,
    sigma_obs: float,
) -> float:
    H_env, H_ve, C_wall, C_room, alpha_eff, T_wall_0, T_room_0 = _to_physical(p)

    # --- prior ---
    def _gauss_nll(mu_pr, sigma_pr, value):
        return 0.5 * ((value - mu_pr) / sigma_pr) ** 2

    nll_prior = (
        _gauss_nll(prior.H_env.mu,     prior.H_env.sigma,     H_env)
        + _gauss_nll(prior.H_ve.mu,    prior.H_ve.sigma,      H_ve)
        + _gauss_nll(prior.C_wall.mu,  prior.C_wall.sigma,    C_wall)
        + _gauss_nll(prior.C_room.mu,  prior.C_room.sigma,    C_room)
        + _gauss_nll(prior.alpha_eff.mu, prior.alpha_eff.sigma, alpha_eff)
        + _gauss_nll(T_obs[0], _SIGMA_IC, T_wall_0)
        + _gauss_nll(T_obs[0], _SIGMA_IC, T_room_0)
    )

    # --- likelihood ---
    A, B = build_state_space(H_env, H_ve, C_wall, C_room, H_int, H_win)
    A_d, B_d = discretize(A, B, dt)
    T_sa = sol_air_temperature(T_ext, G_opaque, alpha_eff)
    x0 = np.array([T_wall_0, T_room_0])
    _, T_pred = forward_sim(A_d, B_d, T_sa, T_ext, Q_room, x0=x0)

    residuals = T_pred - T_obs
    nll_obs = 0.5 * np.sum(residuals ** 2) / sigma_obs ** 2

    return nll_prior + nll_obs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_fit(
    prior: RCModelOut,
    dt: float,
    T_ext: np.ndarray,
    G_opaque: np.ndarray,
    Q_room: np.ndarray,
    T_obs: np.ndarray,
    sigma_obs: float = _SIGMA_OBS,
    timestamps: list[str] | None = None,
) -> FitResult:
    """
    Run MAP fit of the 2R2C model.

    Parameters
    ----------
    prior     : RCModelOut from build_priors — provides Gaussian prior mu/sigma
    dt        : timestep [s] (e.g. 900 for 15 min)
    T_ext     : (N,) outdoor temperature [°C]
    G_opaque  : (N,) area-averaged irradiance on opaque surfaces [W/m²]
                (used to build T_sa inside the optimizer via alpha_eff)
    Q_room    : (N,) direct gains into room air [W] (Q_sol_win + Q_int)
    T_obs     : (N,) observed indoor temperature [°C]
    sigma_obs : observation noise 1-sigma [°C]

    Returns
    -------
    FitResult with MAP estimates and diagnostics
    """
    H_int = prior.H_int
    # H_win is already folded into prior.H_ve (ventilation + window);
    # for the state-space we pass H_win=0 and let H_ve carry the full direct loss.
    H_win = 0.0

    # Initial guess from prior means (clamp alpha away from boundaries)
    alpha0 = float(np.clip(prior.alpha_eff.mu, 0.05, 0.95))
    T0 = float(T_obs[0])
    p0 = _to_unconstrained(
        prior.H_env.mu or 1.0,
        prior.H_ve.mu  or 1.0,
        prior.C_wall.mu or 1e6,
        prior.C_room.mu or 1e6,
        alpha0,
        T0,   # T_wall_0 = T_obs[0]
        T0,   # T_room_0 = T_obs[0]
    )

    result = minimize(
        _neg_log_posterior,
        p0,
        args=(prior, H_int, H_win, dt, G_opaque, T_ext, Q_room, T_obs, sigma_obs),
        method="L-BFGS-B",
        options={"maxiter": 500, "ftol": 1e-10},
    )

    H_env, H_ve, C_wall, C_room, alpha_eff, T_wall_0, T_room_0 = _to_physical(result.x)

    A, B = build_state_space(H_env, H_ve, C_wall, C_room, H_int, H_win)
    A_d, B_d = discretize(A, B, dt)
    T_sa = sol_air_temperature(T_ext, G_opaque, alpha_eff)
    x0 = np.array([T_wall_0, T_room_0])
    T_wall_arr, T_room_arr = forward_sim(A_d, B_d, T_sa, T_ext, Q_room, x0=x0)
    rmse = float(np.sqrt(np.mean((T_room_arr - T_obs) ** 2)))

    return FitResult(
        H_env=H_env,
        H_ve=H_ve,
        C_wall=C_wall,
        C_room=C_room,
        alpha_eff=alpha_eff,
        H_int=H_int,
        T_wall_0=T_wall_0,
        T_room_0=T_room_0,
        success=result.success,
        message=result.message,
        n_obs=len(T_obs),
        residual_rmse=rmse,
        timestamps=timestamps or [],
        T_room_pred=[round(float(v), 4) for v in T_room_arr],
        T_wall_pred=[round(float(v), 4) for v in T_wall_arr],
    )
