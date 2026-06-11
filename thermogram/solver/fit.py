"""Parameter estimation for thermogram — NLS and MCMC.

Param keys use the uniform format  node_id.field_name, e.g.:
  "R_ext.R"                 → resistance node R_ext, field R
  "chambre.C"               → mass node chambre, field C
  "apport_fenetre_sud.gain" → source node apport_fenetre_sud, field gain

All optimisation is done in log-space so parameters stay positive.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .assemble import assemble
from .identifiability import group_params
from .simulate import simulate_zoh


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class FitResult:
    method: str                         # 'nls'
    params_nominal: dict[str, float]    # input nominals
    params_fitted: dict[str, float]     # best-fit values
    params_std: dict[str, float]        # 1-sigma uncertainty (from covariance)
    cost: float                         # final sum-of-squares / 2
    success: bool
    message: str
    elapsed_s: float
    n_evals: int
    param_groups: list[list[str]] = field(default_factory=list)  # identifiability groups


@dataclass
class MCMCResult:
    method: str                         # 'mcmc'
    params_nominal: dict[str, float]
    params_mean: dict[str, float]
    params_std: dict[str, float]
    samples: dict[str, np.ndarray]      # param_key → thinned chain [n_samples]
    acceptance_rate: float
    elapsed_s: float


# ---------------------------------------------------------------------------
# Model patching helpers
# ---------------------------------------------------------------------------

def _parse_key(key: str) -> tuple[str, str]:
    """Split 'node_id.field_name' → (node_id, field_name)."""
    parts = key.split(".", 1)
    if len(parts) != 2:
        raise ValueError(
            f"Param key must be 'node_id.field_name', got: {key!r}"
        )
    return parts[0], parts[1]


def _patch_model(model: dict, params: dict[str, float]) -> dict:
    """Return a deep copy of model with param values applied.

    Supports two key formats:
    - "node_id.field"         — patch a single node field directly
    - "wall_label.R" / ".C"  — fan out to all lump nodes in a chained wall
      (wall_chains entry maps label → {mass_ids, r_ids, chain_n})
    """
    m = copy.deepcopy(model)
    nodes_by_id = {n["id"]: n for n in m["nodes"]}
    wall_chains = m.get("wall_chains", {})

    for key, value in params.items():
        node_id, field_name = _parse_key(key)

        if node_id in wall_chains and field_name in ("R", "C"):
            chain = wall_chains[node_id]
            N = chain["chain_n"]
            if field_name == "C":
                for mid in chain["mass_ids"]:
                    nodes_by_id[mid]["C"] = value / N
            else:  # R — split across interior resistances
                for rid in chain["r_ids"]:
                    nodes_by_id[rid]["R"] = value / N
        elif node_id in nodes_by_id:
            nodes_by_id[node_id][field_name] = value
        else:
            raise ValueError(f"Node '{node_id}' not found in model")
    return m


# ---------------------------------------------------------------------------
# Forward model builder
# ---------------------------------------------------------------------------

def build_forward(
    model: dict,
    inputs: dict[str, tuple[np.ndarray, np.ndarray]],
    observations: dict[str, tuple[np.ndarray, np.ndarray]],
    fit_config: dict,
    start: str,
    end: str,
    dt_minutes: int = 15,
    y0: np.ndarray | None = None,
) -> tuple[
    Callable[[np.ndarray], np.ndarray],
    np.ndarray,
    list[str],
    list[list[str]],
]:
    """Build a forward function for optimisation.

    Inputs and observations must already be fetched (slow I/O done outside).

    Parallel resistors between the same node pair are automatically grouped:
    they share one log-scale multiplier in the optimiser (their ratio stays
    fixed at nominals).  The returned param_keys are one representative key
    per group (the first key in group order); call expand_groups() to map
    fitted group values back to per-node values.

    Parameters
    ----------
    model:
        Model dict (topology stays fixed; only the param fields are patched).
    inputs:
        {node_id: (t_sec, values)} for boundary/source nodes.
    observations:
        {mass_node_id: (t_sec, values)} for observed temperatures.
    fit_config:
        Dict with keys: params, obs_sigma, method.
    start, end:
        ISO-8601 simulation window.
    dt_minutes:
        ZOH time step.
    y0:
        Initial temperatures [°C] for each mass node.  If None, defaults to
        the first boundary value (same as simulate_zoh default).  Pass an
        explicit array when observations start from a known initial condition.

    Returns
    -------
    forward_fn:
        Callable(log_params_vec) → residuals_vec.
        log_params_vec: log-space parameter vector, one entry per group.
        residuals_vec: (T_pred − T_obs) / obs_sigma, concatenated over all
                       observed mass nodes and time steps.
    log_params0:
        Initial log-space parameter vector (log of group nominals).
    group_keys:
        One representative key per group (first key in group), matching the
        vector positions.
    groups:
        Full group list from group_params() — pass to expand_groups() to
        reconstruct all per-node fitted values.
    """
    import datetime
    from scipy.interpolate import interp1d

    params_cfg: dict[str, dict] = fit_config["params"]
    obs_sigma: float = float(fit_config.get("obs_sigma", 0.5))
    all_param_keys = list(params_cfg.keys())

    # Auto-group parallel resistors
    groups = group_params(model, all_param_keys)
    # One representative key per group (first element)
    group_keys = [g[0] for g in groups]
    # Nominal for each group = nominal of representative key
    log_params0 = np.array([np.log(params_cfg[k]["nominal"]) for k in group_keys])

    # Pre-build observation interpolators on the ZOH output grid
    t0 = datetime.datetime.fromisoformat(start).timestamp()
    t1 = datetime.datetime.fromisoformat(end).timestamp()
    dt = dt_minutes * 60.0
    t_grid = np.arange(t0, t1, dt)

    obs_on_grid: dict[str, np.ndarray] = {}
    for mass_id, (t_obs, vals_obs) in observations.items():
        fn = interp1d(
            t_obs, vals_obs,
            kind="linear",
            bounds_error=False,
            fill_value=(vals_obs[0], vals_obs[-1]),
        )
        obs_on_grid[mass_id] = fn(t_grid)

    obs_ids = list(obs_on_grid.keys())

    def forward_fn(log_params_vec: np.ndarray) -> np.ndarray:
        # Expand group multipliers to per-node param values
        params = {}
        for group, log_val in zip(groups, log_params_vec):
            multiplier = np.exp(log_val) / params_cfg[group[0]]["nominal"]
            for key in group:
                params[key] = params_cfg[key]["nominal"] * multiplier
        patched = _patch_model(model, params)
        system = assemble(patched)
        result = simulate_zoh(system, inputs, start, end, dt_minutes=dt_minutes, y0=y0)

        residuals = []
        for mass_id in obs_ids:
            T_pred = result.temps[mass_id]
            T_obs = obs_on_grid[mass_id]
            n = min(len(T_pred), len(T_obs))
            residuals.append((T_pred[:n] - T_obs[:n]) / obs_sigma)
        return np.concatenate(residuals)

    return forward_fn, log_params0, group_keys, groups


def expand_groups(
    groups: list[list[str]],
    group_values: dict[str, float],
    params_cfg: dict[str, dict],
) -> dict[str, float]:
    """Expand fitted group values to per-node values.

    For a group with representative key k and fitted value v, every member m
    in the group gets value: v * (nominal_m / nominal_k).
    Singletons pass through unchanged.
    """
    result = {}
    for group in groups:
        rep = group[0]
        fitted_rep = group_values[rep]
        rep_nominal = params_cfg[rep]["nominal"]
        for key in group:
            result[key] = fitted_rep * (params_cfg[key]["nominal"] / rep_nominal)
    return result


# ---------------------------------------------------------------------------
# NLS
# ---------------------------------------------------------------------------

def fit_nls(
    forward_fn: Callable[[np.ndarray], np.ndarray],
    log_params0: np.ndarray,
    param_keys: list[str],
    fit_config: dict,
    groups: list[list[str]] | None = None,
) -> FitResult:
    """Nonlinear least squares in log-space via scipy.optimize.least_squares.

    Log-normal priors are folded in as extra residual terms so that
    least_squares minimises:
        Σ (T_pred − T_obs)²/σ²  +  Σ (log p − log p_nom)²/σ_log²

    param_keys and log_params0 are the group-level vectors returned by
    build_forward (one entry per group).  groups, if provided, is used to
    expand group-level fitted values back to per-node values in the result.
    """
    from scipy.optimize import least_squares

    params_cfg: dict[str, dict] = fit_config["params"]
    log_nominals = np.array([np.log(params_cfg[k]["nominal"]) for k in param_keys])
    sigma_logs = np.array([params_cfg[k].get("sigma_log", 0.5) for k in param_keys])

    def residuals_with_prior(log_p: np.ndarray) -> np.ndarray:
        data_res = forward_fn(log_p)
        prior_res = (log_p - log_nominals) / sigma_logs
        return np.concatenate([data_res, prior_res])

    t0 = time.perf_counter()
    result = least_squares(
        residuals_with_prior,
        log_params0,
        method="lm",
        ftol=1e-8,
        xtol=1e-8,
        gtol=1e-8,
    )
    elapsed = time.perf_counter() - t0

    # Group-level fitted values
    group_fitted = {k: float(np.exp(v)) for k, v in zip(param_keys, result.x)}

    # Covariance from Jacobian (J^T J)^{-1} * cost / dof
    try:
        J = result.jac
        n_res = len(result.fun)
        n_par = len(param_keys)
        dof = max(n_res - n_par, 1)
        s_sq = 2.0 * result.cost / dof
        cov = np.linalg.pinv(J.T @ J) * s_sq
        std_log = np.sqrt(np.diag(cov))
        group_std = {k: float(np.exp(v) * s) for k, v, s in zip(param_keys, result.x, std_log)}
    except Exception:
        group_std = {k: float("nan") for k in param_keys}

    # Expand groups → per-node results
    if groups is not None:
        params_fitted = expand_groups(groups, group_fitted, params_cfg)
        params_std = expand_groups(groups, group_std, params_cfg)
        params_nominal = {k: params_cfg[k]["nominal"] for g in groups for k in g}
    else:
        params_fitted = group_fitted
        params_std = group_std
        params_nominal = {k: params_cfg[k]["nominal"] for k in param_keys}

    return FitResult(
        method="nls",
        params_nominal=params_nominal,
        params_fitted=params_fitted,
        params_std=params_std,
        cost=float(result.cost),
        success=result.success,
        message=result.message,
        elapsed_s=elapsed,
        n_evals=result.nfev,
        param_groups=groups or [[k] for k in param_keys],
    )


# ---------------------------------------------------------------------------
# MCMC (emcee)
# ---------------------------------------------------------------------------

def fit_mcmc(
    forward_fn: Callable[[np.ndarray], np.ndarray],
    log_params0: np.ndarray,
    param_keys: list[str],
    fit_config: dict,
    n_samples: int = 2000,
    n_walkers: int | None = None,
    groups: list[list[str]] | None = None,
) -> MCMCResult:
    """Ensemble MCMC sampler (emcee) in log-space.

    Log-posterior = Gaussian log-likelihood + log-normal log-prior per param.
    Walkers are initialised around log_params0 (NLS result or nominals).
    param_keys are the group-level keys from build_forward; groups, if
    provided, expands fitted values back to per-node values in the result.
    """
    import emcee

    params_cfg: dict[str, dict] = fit_config["params"]
    log_nominals = np.array([np.log(params_cfg[k]["nominal"]) for k in param_keys])
    sigma_logs = np.array([params_cfg[k].get("sigma_log", 0.5) for k in param_keys])

    n_dim = len(param_keys)
    if n_walkers is None:
        n_walkers = max(2 * n_dim, 8)
    # Ensure even number of walkers (emcee requirement)
    if n_walkers % 2 != 0:
        n_walkers += 1

    def log_posterior(log_p: np.ndarray) -> float:
        log_prior = -0.5 * np.sum(((log_p - log_nominals) / sigma_logs) ** 2)
        res = forward_fn(log_p)
        log_like = -0.5 * float(res @ res)
        return log_prior + log_like

    rng = np.random.default_rng(42)
    p0 = log_params0 + rng.normal(0, 0.05, size=(n_walkers, n_dim))

    sampler = emcee.EnsembleSampler(n_walkers, n_dim, log_posterior)

    t0 = time.perf_counter()
    n_burn = max(n_samples // 5, 50)
    sampler.run_mcmc(p0, n_burn, progress=False)
    sampler.reset()
    sampler.run_mcmc(None, n_samples, progress=False)
    elapsed = time.perf_counter() - t0

    try:
        tau = sampler.get_autocorr_time(quiet=True)
        thin = max(int(np.max(tau) / 2), 1)
    except Exception:
        thin = 1

    flat = sampler.get_chain(flat=True, thin=thin)  # (n_thinned, n_dim)
    acceptance_rate = float(np.mean(sampler.acceptance_fraction))

    # Group-level summaries
    group_mean = {k: float(np.exp(np.mean(flat[:, i]))) for i, k in enumerate(param_keys)}
    group_std = {k: float(np.exp(np.mean(flat[:, i])) * np.std(flat[:, i])) for i, k in enumerate(param_keys)}
    group_samples = {k: np.exp(flat[:, i]) for i, k in enumerate(param_keys)}

    # Expand to per-node if groups provided
    if groups is not None:
        params_mean = expand_groups(groups, group_mean, params_cfg)
        params_std = expand_groups(groups, group_std, params_cfg)
        # Samples: expand each group member's chain from the representative
        samples: dict[str, np.ndarray] = {}
        for g in groups:
            rep = g[0]
            rep_nominal = params_cfg[rep]["nominal"]
            for key in g:
                samples[key] = group_samples[rep] * (params_cfg[key]["nominal"] / rep_nominal)
        params_nominal = {k: params_cfg[k]["nominal"] for g in groups for k in g}
    else:
        params_mean = group_mean
        params_std = group_std
        samples = group_samples
        params_nominal = {k: params_cfg[k]["nominal"] for k in param_keys}

    return MCMCResult(
        method="mcmc",
        params_nominal=params_nominal,
        params_mean=params_mean,
        params_std=params_std,
        samples=samples,
        acceptance_rate=acceptance_rate,
        elapsed_s=elapsed,
    )
