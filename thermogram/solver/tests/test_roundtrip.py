"""Step 1 — Synthetic round-trip test.

Forward-simulate a house with known R_wall / C_wall, inject noise,
then fit with perturbed priors and assert recovery within 10 % (or 2σ).

Run with:  uv run pytest -m roundtrip
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from thermogram.solver.assemble import assemble
from thermogram.solver.fit import build_forward, fit_nls
from thermogram.solver.physics import expand
from thermogram.solver.simulate import simulate_zoh

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    with open(FIXTURES / name) as f:
        return json.load(f)


@pytest.mark.roundtrip
def test_roundtrip_wall_R_and_C():
    """Recover R_wall and C_wall of a chained opaque wall from synthetic data.

    Ground truth comes from expand() on maison_test.json (brick wall + room).
    Priors are perturbed 2× on R, 0.5× on C before fitting.
    Recovery tolerance: 10 % on both parameters.
    """
    rng = np.random.default_rng(0)
    noise_sigma = 0.05  # °C

    house = _load("maison_test.json")
    model, _ = expand(house)

    # Identify the outdoor boundary node id and the room mass node id
    outdoor_node = next(n for n in model["nodes"] if n["kind"] == "boundary")
    room_node = next(n for n in model["nodes"] if n["kind"] == "mass" and "Chambre" in n["label"])
    outdoor_id = outdoor_node["id"]
    room_id = room_node["id"]

    # Ground truth from expand()
    wall_label = "Wall SE"
    chain = model["wall_chains"][wall_label]
    R_true = chain["R_wall"]
    C_true = chain["C_wall"]
    assert R_true > 0 and C_true > 0, "expand() must produce positive R/C"

    # Simulation window: 4 days at 15-min steps
    t0_unix = 0.0
    duration = 4 * 86400.0
    t1_unix = t0_unix + duration
    start = "1970-01-01T00:00:00"

    import datetime
    end = datetime.datetime.fromtimestamp(t1_unix, tz=datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )

    dt_minutes = 15
    dt = dt_minutes * 60.0
    t_sig = np.arange(t0_unix, t1_unix + dt, dt)

    # Synthetic weather: sinusoidal outdoor temperature (diurnal cycle)
    T_outdoor = 5.0 + 8.0 * np.sin(2 * np.pi * t_sig / 86400.0)

    # Build inputs for all boundary and source nodes (solar sources get zero)
    inputs_true = {outdoor_id: (t_sig, T_outdoor)}
    for node in model["nodes"]:
        if node["kind"] == "source":
            inputs_true[node["id"]] = (t_sig, np.zeros_like(t_sig))

    # Forward simulate with ground-truth model
    sys_true = assemble(model)
    n_mass = len([n for n in model["nodes"] if n["kind"] == "mass"])
    result = simulate_zoh(sys_true, inputs_true, start, end, dt_minutes=dt_minutes,
                          y0=np.full(n_mass, T_outdoor[0]))

    obs_t = result.t
    obs_vals = result.temps[room_id] + rng.normal(0, noise_sigma, size=len(result.t))
    observations = {room_id: (obs_t, obs_vals)}

    # Perturbed priors: ×2 on R, ×0.5 on C
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

    rel_err_R = abs(fitted_R - R_true) / R_true
    rel_err_C = abs(fitted_C - C_true) / C_true

    assert rel_err_R < 0.10, (
        f"R recovery failed: fitted={fitted_R:.5f}, true={R_true:.5f}, rel_err={rel_err_R:.1%}"
    )
    assert rel_err_C < 0.10, (
        f"C recovery failed: fitted={fitted_C:.3e}, true={C_true:.3e}, rel_err={rel_err_C:.1%}"
    )
