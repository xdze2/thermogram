"""Tests for solver/fit.py — parameter estimation.

Two checks:
  1. _patch_model correctly applies node_id.field_name params.
  2. fit_nls recovers a known R value on chambre_1r1c synthetic data.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from thermogram.solver.assemble import assemble
from thermogram.solver.fit import _patch_model, build_forward, fit_nls, FitResult
from thermogram.solver.simulate import simulate_zoh

DATA = Path(__file__).parents[3] / "data" / "examples"


def load(name: str) -> dict:
    with open(DATA / name) as f:
        return json.load(f)


def _constant_input(t0: float, t1: float, value: float) -> tuple[np.ndarray, np.ndarray]:
    t = np.linspace(t0, t1, 200)
    return t, np.full(200, value)


class TestPatchModel:
    def setup_method(self):
        self.model = load("chambre_2r2c.json")

    def test_resistance_field(self):
        patched = _patch_model(self.model, {"R_ext.R": 0.999})
        node = next(n for n in patched["nodes"] if n["id"] == "R_ext")
        assert node["R"] == pytest.approx(0.999)

    def test_mass_field(self):
        patched = _patch_model(self.model, {"chambre.C": 12345.0})
        node = next(n for n in patched["nodes"] if n["id"] == "chambre")
        assert node["C"] == pytest.approx(12345.0)

    def test_source_gain(self):
        patched = _patch_model(self.model, {"apport_fenetre_sud.gain": 2.5})
        node = next(n for n in patched["nodes"] if n["id"] == "apport_fenetre_sud")
        assert node["gain"] == pytest.approx(2.5)

    def test_original_unmodified(self):
        original_R = next(n for n in self.model["nodes"] if n["id"] == "R_ext")["R"]
        _patch_model(self.model, {"R_ext.R": 0.999})
        unchanged = next(n for n in self.model["nodes"] if n["id"] == "R_ext")["R"]
        assert unchanged == pytest.approx(original_R)

    def test_unknown_node_raises(self):
        with pytest.raises(ValueError, match="not found"):
            _patch_model(self.model, {"nonexistent.R": 1.0})

    def test_bad_key_format_raises(self):
        from thermogram.solver.fit import _parse_key
        with pytest.raises(ValueError, match="node_id.field_name"):
            _parse_key("R_ext")


class TestFitNLS1R1C:
    """Synthetic recovery test: perturb R by 50%, fit should recover within 5%."""

    def setup_method(self):
        self.model = load("chambre_1r1c.json")
        R_true = 0.034
        C_true = 8_640_000
        self.tau_true = R_true * C_true  # ~293760 s ≈ 81.6 h
        self.R_true = R_true

        # Simulation window: 2 × τ
        t0, t1 = 0.0, 2 * self.tau_true
        self.start = "1970-01-01T00:00:00"
        import datetime
        self.end = datetime.datetime.fromtimestamp(t1, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S")
        self.t0 = t0
        self.t1 = t1

    def _make_inputs(self, t0, t1):
        return {
            "exterior": _constant_input(t0, t1, 10.0),
            "apport_fenetre_sud": _constant_input(t0, t1, 0.0),
        }

    def test_recover_R(self):
        inputs = self._make_inputs(self.t0, self.t1)

        # Synthetic observations: simulate with true model, y0=0
        true_sys = assemble(self.model)
        true_result = simulate_zoh(
            true_sys, inputs, self.start, self.end, dt_minutes=60, y0=np.zeros(1)
        )
        obs_t = true_result.t
        obs_vals = true_result.temps["chambre"]
        observations = {"chambre": (obs_t, obs_vals)}

        fit_config = {
            "params": {
                # Start from 50% off the true value (resistance node is mur_sud)
                "mur_sud.R": {"nominal": self.R_true * 1.5, "sigma_log": 1.0},
            },
            "obs_sigma": 0.01,
            "method": "nls",
        }

        forward_fn, log_p0, param_keys, groups = build_forward(
            self.model, inputs, observations, fit_config,
            self.start, self.end, dt_minutes=60, y0=np.zeros(1),
        )

        result = fit_nls(forward_fn, log_p0, param_keys, fit_config, groups=groups)

        assert isinstance(result, FitResult)
        assert result.success, result.message
        fitted_R = result.params_fitted["mur_sud.R"]
        rel_err = abs(fitted_R - self.R_true) / self.R_true
        assert rel_err < 0.05, (
            f"Fitted R={fitted_R:.5f}, true R={self.R_true:.5f}, rel_err={rel_err:.1%}"
        )
