"""
MAP fit of 2R2C thermal model parameters from observed indoor temperature.

Free parameters (fitted in log-space to enforce positivity):
  theta = [H_env, H_ve, C_wall, C_room, alpha_1, ..., alpha_K]

where alpha_i is the absorptivity for opaque orientation group i.
If only one orientation group is present the result collapses to the original
single-alpha_eff case.

Loss function:
  L(theta) = -log_prior(theta) + 0.5 * ||T_room_pred - T_room_obs||² / sigma_obs²

Gaussian priors come from RCModelOut (output of build_priors).
Each alpha_i uses a logit-transform instead of log (bounded 0–1).

H_int is fixed from ISO 6946 geometry (not fitted).
Window solar gains Q_sol_win = sum(SHGC * A * G_i) per window are computed
externally and passed as Q_room.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize

from .api_models import RCModelOut
from .state_space import build_state_space, discretize, forward_sim


# Observation noise (assumed, 1-sigma) [°C]
_SIGMA_OBS = 0.5

# Prior sigma on initial temperatures [°C]
_SIGMA_IC = 3.0


class FitResult:
    """Posterior MAP estimate for all RC parameters."""

    def __init__(
        self,
        H_env: float,
        H_ve: float,
        C_wall: float,
        C_room: float,
        alpha_eff: float,
        alpha_by_orient: dict[str, float],
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
        self.H_env          = H_env
        self.H_ve           = H_ve
        self.C_wall         = C_wall
        self.C_room         = C_room
        self.alpha_eff      = alpha_eff        # area-weighted scalar (legacy / display)
        self.alpha_by_orient = alpha_by_orient  # {orient_key: alpha_i}
        self.H_int          = H_int
        self.success        = success
        self.message        = message
        self.n_obs          = n_obs
        self.residual_rmse  = residual_rmse
        self.timestamps     = timestamps or []
        self.T_room_pred    = T_room_pred or []
        self.T_wall_pred    = T_wall_pred or []
        self.T_wall_0       = T_wall_0
        self.T_room_0       = T_room_0

    def to_dict(self) -> dict:
        return {
            "H_env":            self.H_env,
            "H_ve":             self.H_ve,
            "C_wall":           self.C_wall,
            "C_room":           self.C_room,
            "alpha_eff":        self.alpha_eff,
            "alpha_by_orient":  self.alpha_by_orient,
            "H_int":            self.H_int,
            "T_wall_0":         self.T_wall_0,
            "T_room_0":         self.T_room_0,
            "success":          self.success,
            "message":          self.message,
            "n_obs":            self.n_obs,
            "residual_rmse":    self.residual_rmse,
            "timestamps":       self.timestamps,
            "T_room_pred":      self.T_room_pred,
            "T_wall_pred":      self.T_wall_pred,
        }


# ---------------------------------------------------------------------------
# Sol-air temperature with per-orientation alphas
# ---------------------------------------------------------------------------

def _weighted_sol_air(
    T_ext: np.ndarray,
    G_by_orient: dict[str, np.ndarray],
    areas_by_orient: dict[str, float],
    alphas: dict[str, float],
    h_ext: float = 25.0,
) -> np.ndarray:
    """
    T_sa = T_ext + (Σ alpha_i * A_i * G_i) / (h_ext * Σ A_i)

    Weighted average sol-air boost over all opaque orientation groups.
    """
    total_area = sum(areas_by_orient.values())
    if total_area == 0:
        return T_ext.copy()
    boost = np.zeros(len(T_ext))
    for key, G in G_by_orient.items():
        a = areas_by_orient.get(key, 0.0)
        alpha = alphas.get(key, 0.0)
        boost += alpha * a * G
    return T_ext + boost / (h_ext * total_area)


# ---------------------------------------------------------------------------
# Parameter transforms (unconstrained ↔ physical)
# ---------------------------------------------------------------------------

def _logit(x: float) -> float:
    return float(np.log(x / (1.0 - x)))


def _sigmoid(x: float) -> float:
    return float(1.0 / (1.0 + np.exp(-x)))


def _to_unconstrained(
    H_env: float, H_ve: float, C_wall: float, C_room: float,
    alphas: list[float], T_wall_0: float, T_room_0: float,
) -> np.ndarray:
    return np.array([
        np.log(H_env),
        np.log(H_ve),
        np.log(C_wall),
        np.log(C_room),
        *[_logit(a) for a in alphas],
        T_wall_0,
        T_room_0,
    ])


def _to_physical(
    p: np.ndarray, n_alpha: int,
) -> tuple[float, float, float, float, list[float], float, float]:
    H_env  = float(np.exp(p[0]))
    H_ve   = float(np.exp(p[1]))
    C_wall = float(np.exp(p[2]))
    C_room = float(np.exp(p[3]))
    alphas = [_sigmoid(float(p[4 + i])) for i in range(n_alpha)]
    T_wall_0 = float(p[4 + n_alpha])
    T_room_0 = float(p[4 + n_alpha + 1])
    return H_env, H_ve, C_wall, C_room, alphas, T_wall_0, T_room_0


# ---------------------------------------------------------------------------
# Loss function
# ---------------------------------------------------------------------------

def _neg_log_posterior(
    p: np.ndarray,
    prior: RCModelOut,
    orient_keys: list[str],
    H_int: float,
    H_win: float,
    dt: float,
    G_by_orient: dict[str, np.ndarray],
    areas_by_orient: dict[str, float],
    T_ext: np.ndarray,
    Q_room: np.ndarray,
    T_obs: np.ndarray,
    sigma_obs: float,
) -> float:
    n_alpha = len(orient_keys)
    H_env, H_ve, C_wall, C_room, alphas, T_wall_0, T_room_0 = _to_physical(p, n_alpha)
    alpha_map = dict(zip(orient_keys, alphas))

    def _gauss_nll(mu_pr, sigma_pr, value):
        return 0.5 * ((value - mu_pr) / sigma_pr) ** 2

    # Prior on RC params (use scalar alpha_eff prior for each alpha_i)
    nll_prior = (
        _gauss_nll(prior.H_env.mu,     prior.H_env.sigma,     H_env)
        + _gauss_nll(prior.H_ve.mu,    prior.H_ve.sigma,      H_ve)
        + _gauss_nll(prior.C_wall.mu,  prior.C_wall.sigma,    C_wall)
        + _gauss_nll(prior.C_room.mu,  prior.C_room.sigma,    C_room)
        + _gauss_nll(T_obs[0], _SIGMA_IC, T_wall_0)
        + _gauss_nll(T_obs[0], _SIGMA_IC, T_room_0)
    )
    for alpha in alphas:
        nll_prior += _gauss_nll(prior.alpha_eff.mu, prior.alpha_eff.sigma, alpha)

    # Likelihood
    T_sa = _weighted_sol_air(T_ext, G_by_orient, areas_by_orient, alpha_map)
    A, B = build_state_space(H_env, H_ve, C_wall, C_room, H_int, H_win)
    A_d, B_d = discretize(A, B, dt)
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
    G_by_orient: dict[str, np.ndarray],
    areas_by_orient: dict[str, float],
    Q_room: np.ndarray,
    T_obs: np.ndarray,
    sigma_obs: float = _SIGMA_OBS,
    timestamps: list[str] | None = None,
) -> FitResult:
    """
    Run MAP fit of the 2R2C model with per-orientation solar absorptivities.

    Parameters
    ----------
    prior          : RCModelOut from build_priors
    dt             : timestep [s]
    T_ext          : (N,) outdoor temperature [°C]
    G_by_orient    : {orient_key: (N,) POA irradiance [W/m²]} for opaque groups
    areas_by_orient: {orient_key: total opaque area [m²]} for weighting
    Q_room         : (N,) direct gains into room air [W] (Q_sol_win + Q_int)
    T_obs          : (N,) observed indoor temperature [°C]
    sigma_obs      : observation noise 1-sigma [°C]

    Returns
    -------
    FitResult with MAP estimates and diagnostics
    """
    H_int = prior.H_int
    H_win = 0.0  # H_win folded into H_ve prior; state-space sees it via H_ve

    orient_keys = list(G_by_orient.keys())

    # If no per-orientation data fall back to a single alpha on a zero-irradiance series
    if not orient_keys:
        orient_keys = ["_flat"]
        G_by_orient = {"_flat": np.zeros(len(T_ext))}
        areas_by_orient = {"_flat": 1.0}

    alpha0 = float(np.clip(prior.alpha_eff.mu, 0.05, 0.95))
    T0 = float(T_obs[0])
    alphas0 = [alpha0] * len(orient_keys)

    p0 = _to_unconstrained(
        prior.H_env.mu or 1.0,
        prior.H_ve.mu  or 1.0,
        prior.C_wall.mu or 1e6,
        prior.C_room.mu or 1e6,
        alphas0,
        T0,
        T0,
    )

    result = minimize(
        _neg_log_posterior,
        p0,
        args=(prior, orient_keys, H_int, H_win, dt,
              G_by_orient, areas_by_orient, T_ext, Q_room, T_obs, sigma_obs),
        method="L-BFGS-B",
        options={"maxiter": 500, "ftol": 1e-10},
    )

    H_env, H_ve, C_wall, C_room, alphas, T_wall_0, T_room_0 = _to_physical(result.x, len(orient_keys))
    alpha_map = dict(zip(orient_keys, alphas))

    # Remove synthetic fallback key from output
    if "_flat" in alpha_map:
        alpha_map = {}

    # Area-weighted scalar for legacy display
    total_area = sum(areas_by_orient.values())
    if total_area > 0 and alpha_map:
        alpha_eff = sum(
            alpha_map[k] * areas_by_orient.get(k, 0.0) for k in alpha_map
        ) / total_area
    else:
        alpha_eff = prior.alpha_eff.mu

    # Forward sim for prediction arrays
    T_sa = _weighted_sol_air(T_ext, G_by_orient, areas_by_orient, alpha_map or {"_flat": alpha_eff})
    A, B = build_state_space(H_env, H_ve, C_wall, C_room, H_int, H_win)
    A_d, B_d = discretize(A, B, dt)
    x0 = np.array([T_wall_0, T_room_0])
    T_wall_arr, T_room_arr = forward_sim(A_d, B_d, T_sa, T_ext, Q_room, x0=x0)
    rmse = float(np.sqrt(np.mean((T_room_arr - T_obs) ** 2)))

    return FitResult(
        H_env=H_env,
        H_ve=H_ve,
        C_wall=C_wall,
        C_room=C_room,
        alpha_eff=alpha_eff,
        alpha_by_orient=alpha_map,
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
