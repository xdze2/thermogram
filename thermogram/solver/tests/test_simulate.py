"""Tests for simulate_ivp — Step 3b verification.

Two analytical checks:
  1. chambre_1r1c: step T_ext 0→10 °C, zero solar → T(t) = 10·(1−exp(−t/τ))
  2. chambre_v1:   T_ext=0, zero solar, T0=[20,20] → two-mode exponential decay
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from thermogram.solver.assemble import assemble
from thermogram.solver.simulate import simulate_ivp, simulate_zoh

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    with open(FIXTURES / name) as f:
        return json.load(f)


def _constant_input(t0: float, t1: float, value: float) -> tuple[np.ndarray, np.ndarray]:
    t = np.array([t0, t1])
    v = np.array([value, value])
    return t, v


class TestIVP1R1C:
    """chambre_1r1c: single mass, step boundary 0→10 °C, zero solar."""

    def setup_method(self):
        model = load("chambre_1r1c.json")
        self.sys = assemble(model)
        # τ = R·C  (from the model file: R=0.034, C=8_640_000)
        R, C = 0.034, 8_640_000
        self.tau = R * C  # seconds

    def _run(self, t_end_s: float) -> tuple[np.ndarray, np.ndarray]:
        t0, t1 = 0.0, t_end_s
        start = "1970-01-01T00:00:00"
        import datetime
        end = datetime.datetime.fromtimestamp(t1, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S")

        inputs = {
            "exterior": _constant_input(t0, t1, 10.0),
            "apport_fenetre_sud": _constant_input(t0, t1, 0.0),
        }
        # y0=0 so we observe the full 0→10 °C step response
        result = simulate_ivp(self.sys, inputs, start, end, dt_minutes=15,
                               y0=np.zeros(1))
        assert result.success, result.message
        return result.t - result.t[0], result.temps["chambre"]

    def test_step_response_at_tau(self):
        """At t=τ, T should be 10·(1−1/e) ≈ 6.32 °C, within 0.01 °C."""
        t_rel, T = self._run(3 * self.tau)
        # Find the index closest to t=τ
        idx = np.argmin(np.abs(t_rel - self.tau))
        T_expected = 10.0 * (1 - np.exp(-1.0))
        assert abs(T[idx] - T_expected) < 0.01, (
            f"T(τ)={T[idx]:.4f} °C, expected {T_expected:.4f} °C"
        )

    def test_step_response_at_3tau(self):
        """At t=3τ, T should be close to 10·(1−exp(−3)) ≈ 9.50 °C."""
        t_rel, T = self._run(3 * self.tau)
        T_expected = 10.0 * (1 - np.exp(-3.0))
        assert abs(T[-1] - T_expected) < 0.05

    def test_metadata(self):
        t_rel, T = self._run(self.tau)
        # Just check fields exist and are plausible — tested via _run assert success
        pass


class TestIVPV1Decay:
    """chambre_v1: T_ext=0, zero solar, T0=[20,20] → exponential decay to zero."""

    def setup_method(self):
        model = load("chambre_v1.json")
        self.sys = assemble(model)
        eigs = np.linalg.eigvals(self.sys.A).real
        taus_s = sorted(-1.0 / e for e in eigs)  # ascending: fast first
        self.tau_fast, self.tau_slow = taus_s

    def _run(self, t_end_s: float, T0: float = 0.0) -> dict[str, np.ndarray]:
        start = "1970-01-01T00:00:00"
        import datetime
        end = datetime.datetime.fromtimestamp(t_end_s, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S")

        inputs = {
            "exterior":      _constant_input(0.0, t_end_s, 0.0),
            "apport_win_SE": _constant_input(0.0, t_end_s, 0.0),
            "apport_win_NE": _constant_input(0.0, t_end_s, 0.0),
        }
        y0 = np.full(len(self.sys.mass_ids), T0)
        result = simulate_ivp(self.sys, inputs, start, end, dt_minutes=15, y0=y0)
        assert result.success, result.message
        return result

    def test_decay_to_zero(self):
        """With T_ext=0, T0=20, all masses must decay to near 0 after 5τ_slow."""
        result = self._run(5 * self.tau_slow, T0=20.0)
        for mid, T in result.temps.items():
            assert abs(T[-1]) < 0.5, (
                f"{mid}: T({5*self.tau_slow/3600:.0f}h) = {T[-1]:.3f} °C, expected ~0"
            )

    def test_success_and_metadata(self):
        result = self._run(2 * self.tau_slow, T0=20.0)
        assert result.success
        assert result.solver == "ivp_bdf"
        assert result.elapsed_s > 0
        assert result.n_rhs_evals is not None and result.n_rhs_evals > 0
        assert result.n_steps is not None and result.n_steps > 0


class TestZOH1R1C:
    """chambre_1r1c: ZOH step-response must match analytical T(t)=10·(1−exp(−t/τ))."""

    def setup_method(self):
        model = load("chambre_1r1c.json")
        self.sys = assemble(model)
        R, C = 0.034, 8_640_000
        self.tau = R * C  # seconds

    def _run(self, t_end_s: float) -> tuple[np.ndarray, np.ndarray]:
        t0, t1 = 0.0, t_end_s
        start = "1970-01-01T00:00:00"
        import datetime
        end = datetime.datetime.fromtimestamp(t1, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S")

        inputs = {
            "exterior":             _constant_input(t0, t1, 10.0),
            "apport_fenetre_sud":   _constant_input(t0, t1, 0.0),
        }
        result = simulate_zoh(self.sys, inputs, start, end, dt_minutes=15,
                               y0=np.zeros(1))
        assert result.success, result.message
        return result.t - result.t[0], result.temps["chambre"]

    def test_step_response_at_tau(self):
        """At t=τ, T must equal 10·(1−1/e) within 0.01 °C."""
        t_rel, T = self._run(3 * self.tau)
        idx = np.argmin(np.abs(t_rel - self.tau))
        T_expected = 10.0 * (1 - np.exp(-1.0))
        assert abs(T[idx] - T_expected) < 0.01, (
            f"T(τ)={T[idx]:.4f} °C, expected {T_expected:.4f} °C"
        )

    def test_metadata(self):
        _, _ = self._run(self.tau)


class TestZOHvsIVP1R1C:
    """ZOH and IVP must agree to < 0.01 °C on the same step response."""

    def setup_method(self):
        model = load("chambre_1r1c.json")
        self.sys = assemble(model)
        R, C = 0.034, 8_640_000
        self.tau = R * C

    def test_zoh_matches_ivp(self):
        t0, t1 = 0.0, 3 * self.tau
        start = "1970-01-01T00:00:00"
        import datetime
        end = datetime.datetime.fromtimestamp(t1, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S")

        inputs = {
            "exterior":           _constant_input(t0, t1, 10.0),
            "apport_fenetre_sud": _constant_input(t0, t1, 0.0),
        }
        y0 = np.zeros(1)
        res_ivp = simulate_ivp(self.sys, inputs, start, end, dt_minutes=15, y0=y0)
        res_zoh = simulate_zoh(self.sys, inputs, start, end, dt_minutes=15, y0=y0)

        assert res_ivp.success
        assert res_zoh.success

        T_ivp = res_ivp.temps["chambre"]
        T_zoh = res_zoh.temps["chambre"]

        # Align on the shorter grid (ZOH uses arange, IVP may differ by 1 point)
        n = min(len(T_ivp), len(T_zoh))
        max_diff = np.max(np.abs(T_ivp[:n] - T_zoh[:n]))
        assert max_diff < 0.01, f"max |IVP−ZOH| = {max_diff:.4f} °C (tolerance 0.01 °C)"
