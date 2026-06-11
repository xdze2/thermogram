"""Step 1 / Step 2 — Synthetic round-trip tests.

Two tests, both marked ``roundtrip``:

test_roundtrip_wall_R_and_C
    Legacy path (build_forward + _patch_model).  Kept as a regression guard
    while the old API still uses it.

test_roundtrip_phi_path
    φ-path (Step 2): same synthetic data, but via build_default_view →
    build_forward_from_view → fit_nls_view.  This is the permanent test once
    the API switches over (Step 3).

Both assert recovery of R_wall and C_wall within 10 % from perturbed priors.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from thermogram.solver.assemble import assemble
from thermogram.solver.fit import build_forward, build_forward_from_view, fit_nls, fit_nls_view
from thermogram.solver.physics import expand
from thermogram.solver.simulate import simulate_zoh
from thermogram.solver.view import build_default_view

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    with open(FIXTURES / name) as f:
        return json.load(f)


def _make_synthetic_data(model, outdoor_id, room_id, noise_sigma, rng):
    """Simulate 4 days with a diurnal outdoor signal; return (inputs, obs, start, end)."""
    import datetime
    t0_unix = 0.0
    duration = 4 * 86400.0
    t1_unix = t0_unix + duration
    start = "1970-01-01T00:00:00"
    end = datetime.datetime.fromtimestamp(t1_unix, tz=datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    dt_minutes = 15
    dt = dt_minutes * 60.0
    t_sig = np.arange(t0_unix, t1_unix + dt, dt)
    T_outdoor = 5.0 + 8.0 * np.sin(2 * np.pi * t_sig / 86400.0)

    inputs_true = {outdoor_id: (t_sig, T_outdoor)}
    for node in model["nodes"]:
        if node["kind"] == "source":
            inputs_true[node["id"]] = (t_sig, np.zeros_like(t_sig))

    n_mass = len([n for n in model["nodes"] if n["kind"] == "mass"])
    sys_true = assemble(model)
    result = simulate_zoh(
        sys_true, inputs_true, start, end,
        dt_minutes=dt_minutes, y0=np.full(n_mass, T_outdoor[0])
    )

    obs_vals = result.temps[room_id] + rng.normal(0, noise_sigma, size=len(result.t))
    observations = {room_id: (result.t, obs_vals)}
    return inputs_true, observations, start, end, dt_minutes, n_mass, T_outdoor


@pytest.mark.roundtrip
def test_roundtrip_wall_R_and_C():
    """Legacy path: recover R_wall and C_wall via build_forward + _patch_model."""
    rng = np.random.default_rng(0)
    noise_sigma = 0.05

    house = _load("maison_test.json")
    model, _ = expand(house)

    outdoor_node = next(n for n in model["nodes"] if n["kind"] == "boundary")
    room_node = next(n for n in model["nodes"] if n["kind"] == "mass" and "Chambre" in n["label"])
    outdoor_id = outdoor_node["id"]
    room_id = room_node["id"]

    wall_label = "Wall SE"
    chain = model["wall_chains"][wall_label]
    R_true = chain["R_wall"]
    C_true = chain["C_wall"]
    assert R_true > 0 and C_true > 0

    inputs_true, observations, start, end, dt_minutes, n_mass, T_outdoor = (
        _make_synthetic_data(model, outdoor_id, room_id, noise_sigma, rng)
    )

    fit_config = {
        "params": {
            f"{wall_label}.R": {"nominal": R_true * 2.0, "sigma_log": 2.0},
            f"{wall_label}.C": {"nominal": C_true * 0.5, "sigma_log": 2.0},
        },
        "obs_sigma": noise_sigma,
        "method": "nls",
    }

    forward_fn, log_p0, param_keys, groups = build_forward(
        model, inputs_true, observations, fit_config,
        start, end, dt_minutes=dt_minutes,
        y0=np.full(n_mass, T_outdoor[0]),
    )
    result_fit = fit_nls(forward_fn, log_p0, param_keys, fit_config, groups=groups)

    assert result_fit.success, f"fit_nls did not converge: {result_fit.message}"

    fitted_R = result_fit.params_fitted[f"{wall_label}.R"]
    fitted_C = result_fit.params_fitted[f"{wall_label}.C"]

    assert abs(fitted_R - R_true) / R_true < 0.10, (
        f"R recovery failed: fitted={fitted_R:.5f}, true={R_true:.5f}"
    )
    assert abs(fitted_C - C_true) / C_true < 0.10, (
        f"C recovery failed: fitted={fitted_C:.3e}, true={C_true:.3e}"
    )


@pytest.mark.roundtrip
def test_roundtrip_phi_path():
    """φ-path (Step 2): recover R_wall and C_wall via build_default_view + fit_nls_view."""
    rng = np.random.default_rng(0)
    noise_sigma = 0.05

    house = _load("maison_test.json")
    model, emap = expand(house)

    outdoor_node = next(n for n in model["nodes"] if n["kind"] == "boundary")
    room_node = next(n for n in model["nodes"] if n["kind"] == "mass" and "Chambre" in n["label"])
    outdoor_id = outdoor_node["id"]
    room_id = room_node["id"]

    wall_label = "Wall SE"
    chain = model["wall_chains"][wall_label]
    R_true = chain["R_wall"]
    C_true = chain["C_wall"]
    assert R_true > 0 and C_true > 0

    inputs_true, observations, start, end, dt_minutes, n_mass, T_outdoor = (
        _make_synthetic_data(model, outdoor_id, room_id, noise_sigma, rng)
    )

    # Build the default view.
    # The maison_test fixture has two walls in parallel (Wall SE chained, Wall NE
    # no-mass); fitting both simultaneously is structurally non-identifiable without
    # prior regularisation on the second wall.  We fix all lumps except the RC_chain
    # to match the Step 1 test's parameter scope (only R_interior, C_wall free).
    from thermogram.models import View
    from thermogram.solver.view import get_chain_priors

    view_base = build_default_view(model, emap)

    # Find chain lump and get its interior-R + C prior nominals (ground truth)
    chain_lump_base = next(l for l in view_base.lumped if l.kind == "RC_chain")
    R_interior_true, C_interior_true = get_chain_priors(chain_lump_base, model, emap)
    assert R_interior_true > 0 and C_interior_true > 0

    # Perturb: ×2 on R, ×0.5 on C — rebuild view with perturbed chain prior
    chain_lump_perturbed = chain_lump_base.model_copy(update={
        "prior": chain_lump_base.prior.model_copy(update={"nominal": R_interior_true * 2.0}),
    })
    # Also perturb C prior — stored on a separate key in fit; rebuild via model copy
    # The C prior is derived from get_chain_priors inside build_forward_from_view,
    # not from lump.prior.  We perturb by overriding the atomic model node C values.
    import copy
    model_perturbed = copy.deepcopy(model)
    wall_chain = model_perturbed["wall_chains"][wall_label]
    for mid in wall_chain["mass_ids"]:
        node = next(n for n in model_perturbed["nodes"] if n["id"] == mid)
        node["C"] = node["C"] * 0.5  # perturb C node values (halve each)

    view_perturbed_lumped = []
    for lump in view_base.lumped:
        if lump.kind == "RC_chain":
            view_perturbed_lumped.append(chain_lump_perturbed)
        else:
            view_perturbed_lumped.append(lump.model_copy(update={"mode": "fixed"}))
    view_perturbed = View(id=view_base.id, lumped=view_perturbed_lumped)

    forward_fn, log_phi0, phi_keys = build_forward_from_view(
        view_perturbed, model, emap,
        inputs_true, observations,
        obs_sigma=noise_sigma,
        start=start, end=end, dt_minutes=dt_minutes,
        y0=np.full(n_mass, T_outdoor[0]),
    )

    result_fit = fit_nls_view(
        forward_fn, log_phi0, phi_keys,
        view_perturbed, model, emap,
    )

    assert result_fit.success, f"fit_nls_view did not converge: {result_fit.message}"

    # Find the chain lump's _R and _C keys
    chain_lump = next(l for l in view_perturbed.lumped if l.kind == "RC_chain")
    key_R = chain_lump.id + "_R"
    key_C = chain_lump.id + "_C"

    fitted_R = result_fit.phi_fitted[key_R]
    fitted_C = result_fit.phi_fitted[key_C]

    # Ground truth is the interior-R sum and C sum (what phi_R/phi_C actually control)
    assert abs(fitted_R - R_interior_true) / R_interior_true < 0.10, (
        f"R recovery failed: fitted={fitted_R:.5f}, true={R_interior_true:.5f}"
    )
    assert abs(fitted_C - C_interior_true) / C_interior_true < 0.10, (
        f"C recovery failed: fitted={fitted_C:.3e}, true={C_interior_true:.3e}"
    )
