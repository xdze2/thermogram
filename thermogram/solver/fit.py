"""Parameter estimation for thermogram — NLS and MCMC.

Two entry points:

build_forward_from_view(view, atomic_model, ...)
    The new φ-space path (Step 2).  Takes a View of LumpedElements; the
    residual closure maps log-φ → atom values (via combine rules) → patched
    atomic model → assemble → simulate.  Posteriors land on lumped element ids.

build_forward(atomic_model, ...)
    Legacy path: param keys in 'node_id.field_name' format.  Kept for the
    API and tests that haven't switched to Views yet.

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


def _patch_model(atomic_model: dict, params: dict[str, float]) -> dict:
    """Return a deep copy of atomic_model with param values applied.

    Supports two key formats:
    - "node_id.field"         — patch a single node field directly
    - "wall_label.R" / ".C"  — fan out to all lump nodes in a chained wall
      (wall_chains entry maps label → {mass_ids, r_ids, chain_n})
    """
    m = copy.deepcopy(atomic_model)
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
            raise ValueError(f"Node '{node_id}' not found in atomic_model")
    return m


# ---------------------------------------------------------------------------
# Forward model builder
# ---------------------------------------------------------------------------

def build_forward(
    atomic_model: dict,
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
    atomic_model:
        Atomic model dict (topology stays fixed; only the param fields are patched).
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
    groups = group_params(atomic_model, all_param_keys)
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
        patched = _patch_model(atomic_model, params)
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


# ---------------------------------------------------------------------------
# φ-space forward model (Step 2) — build_forward_from_view
# ---------------------------------------------------------------------------

@dataclass
class ViewFitResult:
    """fit_nls / fit_mcmc result in φ-space: posteriors keyed by lumped element id."""
    method: str
    # φ-space posteriors: lump_id → (fitted_value, sigma)
    # For RC_chain: lump_id → (R_fitted, C_fitted); sigma keyed as lump_id+"_R" / "_C"
    phi_fitted: dict[str, float]      # lump_id (+ "_R"/"_C" for chains) → value
    phi_std: dict[str, float]         # same keys → 1-sigma
    phi_nominal: dict[str, float]     # same keys → prior nominal
    cost: float
    success: bool
    message: str
    elapsed_s: float
    n_evals: int
    # Ordered list of φ keys matching the log_params vector
    phi_keys: list[str]


def build_forward_from_view(
    view,                                              # thermogram.models.View
    atomic_model: dict,
    expansion_map: dict[str, list[str]],
    inputs: dict[str, tuple[np.ndarray, np.ndarray]],
    observations: dict[str, tuple[np.ndarray, np.ndarray]],
    obs_sigma: float = 0.5,
    start: str = "1970-01-01T00:00:00",
    end: str = "1970-01-01T00:00:00",
    dt_minutes: int = 15,
    y0: np.ndarray | None = None,
) -> tuple[
    Callable[[np.ndarray], np.ndarray],
    np.ndarray,
    list[str],
]:
    """Build a φ-space forward function from a View.

    Free lumped elements become entries in the log-φ vector.  RC_chain
    elements contribute *two* entries (R_total, C_total) with keys
    ``lump_id + "_R"`` and ``lump_id + "_C"``.

    Fixed lumped elements are held at their prior nominal (not in the vector).

    Parameters
    ----------
    view:           View of LumpedElements.
    atomic_model:   Atomic model dict from expand().
    expansion_map:  {elem_uuid: [atom_ids]} from expand().
    inputs:         {atom_node_id: (t_sec, values)}.
    observations:   {mass_node_id: (t_sec, values)}.
    obs_sigma:      Observation noise std [°C].
    start, end:     ISO-8601 simulation window.
    dt_minutes:     ZOH time step.
    y0:             Initial temperatures per mass node; None ⇒ first boundary value.

    Returns
    -------
    forward_fn:   Callable(log_phi_vec) → residuals.
    log_phi0:     Initial log-φ vector (log of prior nominals).
    phi_keys:     List of φ key strings, one-to-one with log_phi_vec entries.
    """
    import datetime
    from scipy.interpolate import interp1d
    from thermogram.solver.lumps import (
        ChainAtoms,
        apply_atom_values,
        expand_lumped,
    )
    from thermogram.solver.view import chain_atoms_for_lump, get_chain_priors

    # --- Build ordered φ key list and nominal vector ---
    phi_keys: list[str] = []
    log_phi0_list: list[float] = []

    # Per-lump metadata needed inside the closure
    lump_meta: list[dict] = []  # one entry per free lump

    for lump in view.lumped:
        if lump.mode == "fixed":
            continue
        if lump.kind == "RC_chain":
            R_nom, C_nom = get_chain_priors(lump, atomic_model, expansion_map)
            phi_keys.append(lump.id + "_R")
            phi_keys.append(lump.id + "_C")
            log_phi0_list.append(np.log(R_nom))
            log_phi0_list.append(np.log(C_nom))
            ca = chain_atoms_for_lump(lump, atomic_model, expansion_map)
            lump_meta.append({
                "lump": lump,
                "kind": "chain",
                "key_R": lump.id + "_R",
                "key_C": lump.id + "_C",
                "R_nom": R_nom,
                "C_nom": C_nom,
                "sigma_log_R": lump.prior.sigma_log,
                "sigma_log_C": lump.prior_C.sigma_log if lump.prior_C is not None else lump.prior.sigma_log,
                "chain_atoms": ca,
            })
        else:
            phi_keys.append(lump.id)
            log_phi0_list.append(np.log(lump.prior.nominal))
            # Collect atom nominals for weighted combine rules
            nodes_by_id = {n["id"]: n for n in atomic_model["nodes"]}
            field_map = {"mass": "C", "resistance": "R", "source": "gain"}
            atom_noms = []
            for aid in lump.atoms:
                node = nodes_by_id.get(aid, {})
                fname = field_map.get(node.get("kind", ""), None)
                atom_noms.append(node[fname] if fname else 1.0)
            lump_meta.append({
                "lump": lump,
                "kind": "scalar",
                "key": lump.id,
                "nominal": lump.prior.nominal,
                "sigma_log": lump.prior.sigma_log,
                "atom_noms": atom_noms,
            })

    log_phi0 = np.array(log_phi0_list)

    # --- Fixed-lump atom values (constant for all iterations) ---
    fixed_atom_values: dict[str, float] = {}
    nodes_by_id = {n["id"]: n for n in atomic_model["nodes"]}
    field_map_fixed = {"mass": "C", "resistance": "R", "source": "gain", "boundary": "T_source"}
    for lump in view.lumped:
        if lump.mode != "fixed":
            continue
        # Use prior nominal as the fixed value for numeric fields.
        # Boundary nodes with signal T_source are not patched (already in model).
        for aid in lump.atoms:
            node = nodes_by_id.get(aid, {})
            fname = field_map_fixed.get(node.get("kind", ""), None)
            if fname and fname != "T_source" and isinstance(node.get(fname), (int, float)):
                fixed_atom_values[aid] = float(node[fname])

    # --- Observation interpolators ---
    t0_ts = datetime.datetime.fromisoformat(start).timestamp()
    t1_ts = datetime.datetime.fromisoformat(end).timestamp()
    dt = dt_minutes * 60.0
    t_grid = np.arange(t0_ts, t1_ts, dt)

    obs_on_grid: dict[str, np.ndarray] = {}
    for mass_id, (t_obs, vals_obs) in observations.items():
        fn = interp1d(
            t_obs, vals_obs,
            kind="linear", bounds_error=False,
            fill_value=(vals_obs[0], vals_obs[-1]),
        )
        obs_on_grid[mass_id] = fn(t_grid)
    obs_ids = list(obs_on_grid.keys())

    # --- Prior residuals metadata ---
    # Collected in the same order as phi_keys
    prior_nominals = np.array([np.exp(v) for v in log_phi0])
    prior_sigma_logs: list[float] = []
    for meta in lump_meta:
        if meta["kind"] == "chain":
            prior_sigma_logs.append(meta["sigma_log_R"])
            prior_sigma_logs.append(meta["sigma_log_C"])
        else:
            prior_sigma_logs.append(meta["sigma_log"])
    prior_sigma_logs_arr = np.array(prior_sigma_logs)

    # --- Forward closure ---
    def forward_fn(log_phi_vec: np.ndarray) -> np.ndarray:
        # Build {atom_id: value} from free lumps
        atom_values: dict[str, float] = dict(fixed_atom_values)

        idx = 0
        for meta in lump_meta:
            lump = meta["lump"]
            if meta["kind"] == "chain":
                phi_R = float(np.exp(log_phi_vec[idx]))
                phi_C = float(np.exp(log_phi_vec[idx + 1]))
                idx += 2
                av = expand_lumped(lump, (phi_R, phi_C), chain_atoms=meta["chain_atoms"])
            else:
                phi = float(np.exp(log_phi_vec[idx]))
                idx += 1
                av = expand_lumped(lump, phi, atom_nominals=meta["atom_noms"])
            atom_values.update(av)

        patched = apply_atom_values(atomic_model, atom_values)
        system = assemble(patched)
        result = simulate_zoh(system, inputs, start, end, dt_minutes=dt_minutes, y0=y0)

        residuals = []
        for mass_id in obs_ids:
            T_pred = result.temps[mass_id]
            T_obs = obs_on_grid[mass_id]
            n = min(len(T_pred), len(T_obs))
            residuals.append((T_pred[:n] - T_obs[:n]) / obs_sigma)
        return np.concatenate(residuals)

    return forward_fn, log_phi0, phi_keys


def fit_nls_view(
    forward_fn: Callable[[np.ndarray], np.ndarray],
    log_phi0: np.ndarray,
    phi_keys: list[str],
    view,                           # thermogram.models.View
    atomic_model: dict,
    expansion_map: dict[str, list[str]],
) -> "ViewFitResult":
    """NLS fit in φ-space; posteriors keyed by lumped element id.

    Wraps fit_nls and maps the result back to ViewFitResult with the
    phi_fitted / phi_std keyed by lump id (+ "_R"/"_C" for chains).
    """
    from scipy.optimize import least_squares
    from thermogram.solver.view import get_chain_priors

    # Reconstruct prior nominals and sigma_logs in phi_keys order
    phi_nominal: dict[str, float] = {}
    phi_sigma_log: dict[str, float] = {}
    for lump in view.lumped:
        if lump.mode == "fixed":
            continue
        if lump.kind == "RC_chain":
            R_nom, C_nom = get_chain_priors(lump, atomic_model, expansion_map)
            phi_nominal[lump.id + "_R"] = R_nom
            phi_nominal[lump.id + "_C"] = C_nom
            phi_sigma_log[lump.id + "_R"] = lump.prior.sigma_log
            phi_sigma_log[lump.id + "_C"] = lump.prior_C.sigma_log if lump.prior_C is not None else lump.prior.sigma_log
        else:
            phi_nominal[lump.id] = lump.prior.nominal
            phi_sigma_log[lump.id] = lump.prior.sigma_log

    log_nominals = np.array([np.log(phi_nominal[k]) for k in phi_keys])
    sigma_logs = np.array([phi_sigma_log[k] for k in phi_keys])

    def residuals_with_prior(log_p: np.ndarray) -> np.ndarray:
        data_res = forward_fn(log_p)
        prior_res = (log_p - log_nominals) / sigma_logs
        return np.concatenate([data_res, prior_res])

    t0 = time.perf_counter()
    result = least_squares(
        residuals_with_prior, log_phi0,
        method="lm", ftol=1e-8, xtol=1e-8, gtol=1e-8,
    )
    elapsed = time.perf_counter() - t0

    phi_fitted = {k: float(np.exp(v)) for k, v in zip(phi_keys, result.x)}

    try:
        J = result.jac
        n_res, n_par = len(result.fun), len(phi_keys)
        dof = max(n_res - n_par, 1)
        s_sq = 2.0 * result.cost / dof
        cov = np.linalg.pinv(J.T @ J) * s_sq
        std_log = np.sqrt(np.diag(cov))
        phi_std = {k: float(np.exp(v) * s) for k, v, s in zip(phi_keys, result.x, std_log)}
    except Exception:
        phi_std = {k: float("nan") for k in phi_keys}

    return ViewFitResult(
        method="nls",
        phi_fitted=phi_fitted,
        phi_std=phi_std,
        phi_nominal=phi_nominal,
        cost=float(result.cost),
        success=result.success,
        message=result.message,
        elapsed_s=elapsed,
        n_evals=result.nfev,
        phi_keys=phi_keys,
    )
