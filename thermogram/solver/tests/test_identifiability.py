"""Tests for solver/identifiability.py — auto-grouping of parallel resistors."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from thermogram.solver.identifiability import group_params
from thermogram.solver.fit import build_forward, fit_nls, expand_groups

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    with open(FIXTURES / name) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# group_params unit tests
# ---------------------------------------------------------------------------

class TestGroupParams:
    def test_single_resistance_is_singleton(self):
        model = load("chambre_1r1c.json")
        groups = group_params(model, ["mur_sud.R"])
        assert groups == [["mur_sud.R"]]

    def test_series_chain_singletons(self):
        # chambre_2r2c: R_ext → mur_sud (mass) → R_int → chambre
        # R_ext and R_int connect different endpoint pairs — should stay singletons
        model = load("chambre_2r2c.json")
        keys = ["R_ext.R", "R_int.R"]
        groups = group_params(model, keys)
        assert groups == [["R_ext.R"], ["R_int.R"]]

    def test_parallel_resistors_grouped(self):
        # chambre_v1: R_roof, R_walls_ins, R_win_SE, R_win_NE all connect
        # exterior → chambre in parallel.
        model = load("chambre_v1.json")
        keys = ["R_roof.R", "R_walls_ins.R", "R_win_SE.R", "R_win_NE.R"]
        groups = group_params(model, keys)
        # All four should be in one group
        assert len(groups) == 1
        assert set(groups[0]) == {"R_roof.R", "R_walls_ins.R", "R_win_SE.R", "R_win_NE.R"}

    def test_partial_parallel_grouped(self):
        # Only some parallel keys are free; series R_wall_SE_ext stays separate
        model = load("chambre_v1.json")
        keys = ["R_roof.R", "R_win_SE.R", "R_wall_SE_ext.R"]
        groups = group_params(model, keys)
        # R_roof and R_win_SE are parallel (exterior→chambre); R_wall_SE_ext is not
        parallel_group = next(g for g in groups if len(g) > 1)
        assert set(parallel_group) == {"R_roof.R", "R_win_SE.R"}
        singleton = next(g for g in groups if "R_wall_SE_ext.R" in g)
        assert singleton == ["R_wall_SE_ext.R"]

    def test_non_resistance_always_singleton(self):
        model = load("chambre_v1.json")
        keys = ["R_roof.R", "chambre.C", "apport_win_SE.gain"]
        groups = group_params(model, keys)
        # chambre.C and apport_win_SE.gain must be singletons
        singleton_keys = [g[0] for g in groups if len(g) == 1]
        assert "chambre.C" in singleton_keys
        assert "apport_win_SE.gain" in singleton_keys

    def test_order_preserved(self):
        model = load("chambre_v1.json")
        keys = ["R_win_NE.R", "R_roof.R", "chambre.C"]
        groups = group_params(model, keys)
        # chambre.C is singleton; the two parallel R keys form one group
        # Group order should follow first occurrence in keys
        flat = [k for g in groups for k in g]
        # R_win_NE appears before R_roof in input, so it should be representative
        rep = next(g[0] for g in groups if len(g) == 2)
        assert rep == "R_win_NE.R"


# ---------------------------------------------------------------------------
# expand_groups
# ---------------------------------------------------------------------------

class TestExpandGroups:
    def test_singleton_passthrough(self):
        groups = [["R_ext.R"], ["chambre.C"]]
        params_cfg = {"R_ext.R": {"nominal": 0.1}, "chambre.C": {"nominal": 1e6}}
        fitted = {"R_ext.R": 0.2, "chambre.C": 2e6}
        result = expand_groups(groups, fitted, params_cfg)
        assert result == {"R_ext.R": pytest.approx(0.2), "chambre.C": pytest.approx(2e6)}

    def test_group_scales_by_ratio(self):
        # Two parallel R with nominals 0.1 and 0.2; representative is first.
        # Fitted representative = 0.3 (3× nominal 0.1).
        # Second member should get 0.6 (3× its nominal 0.2).
        groups = [["R_a.R", "R_b.R"]]
        params_cfg = {"R_a.R": {"nominal": 0.1}, "R_b.R": {"nominal": 0.2}}
        fitted = {"R_a.R": 0.3}
        result = expand_groups(groups, fitted, params_cfg)
        assert result["R_a.R"] == pytest.approx(0.3)
        assert result["R_b.R"] == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# Integration: build_forward groups parallel Rs on chambre_v1
# ---------------------------------------------------------------------------

def _constant_input(t0: float, t1: float, value: float):
    t = np.linspace(t0, t1, 200)
    return t, np.full(200, value)


class TestBuildForwardGrouping:
    def test_grouped_model_reduces_dof(self):
        model = load("chambre_v1.json")
        t0, t1 = 0.0, 86400.0
        start = "1970-01-01T00:00:00"
        end = "1970-01-02T00:00:00"

        inputs = {
            "exterior":      _constant_input(t0, t1, 5.0),
            "apport_win_SE": _constant_input(t0, t1, 0.0),
            "apport_win_NE": _constant_input(t0, t1, 0.0),
        }
        obs = {"chambre": _constant_input(t0, t1, 10.0)}

        fit_config = {
            "params": {
                "R_roof.R":      {"nominal": 0.2354, "sigma_log": 0.5},
                "R_walls_ins.R": {"nominal": 0.0738, "sigma_log": 0.5},
                "R_win_SE.R":    {"nominal": 0.2381, "sigma_log": 0.5},
                "R_win_NE.R":    {"nominal": 0.5952, "sigma_log": 0.5},
            },
            "obs_sigma": 0.5,
            "method": "nls",
        }

        forward_fn, log_p0, group_keys, groups = build_forward(
            model, inputs, obs, fit_config, start, end, dt_minutes=60,
        )

        # 4 parallel R keys → 1 group → 1 DOF
        assert len(group_keys) == 1
        assert len(groups) == 1
        assert len(log_p0) == 1
        assert set(groups[0]) == {"R_roof.R", "R_walls_ins.R", "R_win_SE.R", "R_win_NE.R"}

    def test_fit_nls_expands_groups(self):
        model = load("chambre_v1.json")
        t0, t1 = 0.0, 86400.0
        start = "1970-01-01T00:00:00"
        end = "1970-01-02T00:00:00"

        inputs = {
            "exterior":      _constant_input(t0, t1, 5.0),
            "apport_win_SE": _constant_input(t0, t1, 0.0),
            "apport_win_NE": _constant_input(t0, t1, 0.0),
        }
        obs = {"chambre": _constant_input(t0, t1, 10.0)}

        fit_config = {
            "params": {
                "R_roof.R":      {"nominal": 0.2354, "sigma_log": 0.5},
                "R_walls_ins.R": {"nominal": 0.0738, "sigma_log": 0.5},
                "R_win_SE.R":    {"nominal": 0.2381, "sigma_log": 0.5},
                "R_win_NE.R":    {"nominal": 0.5952, "sigma_log": 0.5},
            },
            "obs_sigma": 0.5,
            "method": "nls",
        }

        forward_fn, log_p0, group_keys, groups = build_forward(
            model, inputs, obs, fit_config, start, end, dt_minutes=60,
        )
        result = fit_nls(forward_fn, log_p0, group_keys, fit_config, groups=groups)

        # Result should report all 4 per-node keys, not just the group representative
        assert set(result.params_fitted.keys()) == {
            "R_roof.R", "R_walls_ins.R", "R_win_SE.R", "R_win_NE.R"
        }
        # Ratios must be preserved: fitted[k] / nominal[k] == same multiplier for all
        multipliers = [
            result.params_fitted[k] / fit_config["params"][k]["nominal"]
            for k in ["R_roof.R", "R_walls_ins.R", "R_win_SE.R", "R_win_NE.R"]
        ]
        assert all(abs(m - multipliers[0]) < 1e-9 for m in multipliers)
        # param_groups carried through
        assert result.param_groups == groups
