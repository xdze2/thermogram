"""Unit tests for solver/lumps.py — combine rules and phi↔atom round-trips."""

from __future__ import annotations

import pytest
from thermogram.solver.lumps import (
    apply_chain,
    apply_identity,
    apply_parallel_inv_sum,
    apply_parallel_sum,
    apply_series_sum,
    apply_atom_values,
    compose_chain_prior,
    compose_parallel_inv_prior,
    compose_parallel_sum_prior,
    compose_series_prior,
    expand_lumped,
)
from thermogram.models import LumpedElement, Prior


# ---------------------------------------------------------------------------
# series_sum
# ---------------------------------------------------------------------------

class TestSeriesSum:
    def test_single_atom_at_prior(self):
        result = apply_series_sum(10.0, ["a"], [10.0])
        assert result == {"a": pytest.approx(10.0)}

    def test_two_atoms_equal_nominals(self):
        result = apply_series_sum(6.0, ["a", "b"], [3.0, 3.0])
        assert result["a"] == pytest.approx(3.0)
        assert result["b"] == pytest.approx(3.0)

    def test_two_atoms_unequal_nominals(self):
        result = apply_series_sum(6.0, ["a", "b"], [2.0, 4.0])
        assert result["a"] == pytest.approx(2.0)
        assert result["b"] == pytest.approx(4.0)

    def test_scale_up(self):
        result = apply_series_sum(12.0, ["a", "b"], [2.0, 4.0])
        assert result["a"] == pytest.approx(4.0)
        assert result["b"] == pytest.approx(8.0)

    def test_phi_equals_prior_sum_gives_nominals(self):
        noms = [1.5, 2.5, 3.0]
        phi = sum(noms)
        result = apply_series_sum(phi, ["a", "b", "c"], noms)
        for aid, nom in zip(["a", "b", "c"], noms):
            assert result[aid] == pytest.approx(nom)

    def test_atom_sum_equals_phi(self):
        result = apply_series_sum(7.0, ["x", "y"], [2.0, 5.0])
        assert sum(result.values()) == pytest.approx(7.0)


# ---------------------------------------------------------------------------
# parallel_sum
# ---------------------------------------------------------------------------

class TestParallelSum:
    def test_phi_equals_prior_sum_gives_nominals(self):
        noms = [100.0, 200.0, 300.0]
        phi = sum(noms)
        result = apply_parallel_sum(phi, ["a", "b", "c"], noms)
        for aid, nom in zip(["a", "b", "c"], noms):
            assert result[aid] == pytest.approx(nom)

    def test_atom_sum_equals_phi(self):
        result = apply_parallel_sum(1000.0, ["x", "y"], [400.0, 600.0])
        assert sum(result.values()) == pytest.approx(1000.0)

    def test_scale_down(self):
        result = apply_parallel_sum(300.0, ["a", "b"], [200.0, 400.0])
        # w_a = 1/3, w_b = 2/3
        assert result["a"] == pytest.approx(100.0)
        assert result["b"] == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# parallel_inv_sum
# ---------------------------------------------------------------------------

class TestParallelInvSum:
    def test_phi_equals_parallel_nominal_gives_nominals(self):
        noms = [2.0, 4.0]
        # phi_nom = 1/sum(1/R_i) = 1/(0.5+0.25) = 4/3
        phi = 1.0 / sum(1.0 / r for r in noms)
        result = apply_parallel_inv_sum(phi, ["a", "b"], noms)
        assert result["a"] == pytest.approx(noms[0])
        assert result["b"] == pytest.approx(noms[1])

    def test_parallel_combination_invariant(self):
        """1/phi == sum(1/R_atom_i) for any phi."""
        result = apply_parallel_inv_sum(3.0, ["a", "b"], [4.0, 8.0])
        computed_phi = 1.0 / sum(1.0 / v for v in result.values())
        assert computed_phi == pytest.approx(3.0)

    def test_single_atom(self):
        result = apply_parallel_inv_sum(5.0, ["a"], [5.0])
        assert result["a"] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# chain
# ---------------------------------------------------------------------------

class TestChain:
    def test_equal_distribution_R(self):
        result = apply_chain(6.0, 0.0, ["r0", "r1", "r2"], [])
        assert result["r0"] == pytest.approx(2.0)
        assert result["r1"] == pytest.approx(2.0)
        assert result["r2"] == pytest.approx(2.0)

    def test_equal_distribution_C(self):
        result = apply_chain(0.0, 9.0, [], ["c0", "c1", "c2"])
        assert result["c0"] == pytest.approx(3.0)
        assert result["c1"] == pytest.approx(3.0)
        assert result["c2"] == pytest.approx(3.0)

    def test_sum_equals_phi(self):
        r_ids = ["r0", "r1"]
        c_ids = ["c0", "c1", "c2"]
        result = apply_chain(10.0, 30.0, r_ids, c_ids)
        assert sum(result[k] for k in r_ids) == pytest.approx(10.0)
        assert sum(result[k] for k in c_ids) == pytest.approx(30.0)

    def test_empty_lists(self):
        result = apply_chain(5.0, 10.0, [], [])
        assert result == {}


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------

class TestIdentity:
    def test_passthrough(self):
        result = apply_identity(42.0, "x")
        assert result == {"x": pytest.approx(42.0)}


# ---------------------------------------------------------------------------
# expand_lumped — high-level dispatch
# ---------------------------------------------------------------------------

def _make_lump(combine, atoms, kind="Req", nominal=1.0, n=None):
    return LumpedElement(
        id="test_lump",
        kind=kind,
        atoms=atoms,
        combine=combine,
        prior=Prior(nominal=nominal, sigma_log=0.5),
        n=n,
    )


class TestExpandLumped:
    def test_identity_lump(self):
        lump = _make_lump("identity", ["a"], kind="T_boundary", nominal=20.0)
        result = expand_lumped(lump, 15.0)
        assert result == {"a": pytest.approx(15.0)}

    def test_series_sum_at_prior(self):
        lump = _make_lump("series_sum", ["a", "b"], kind="Req", nominal=6.0)
        result = expand_lumped(lump, 6.0, atom_nominals=[2.0, 4.0])
        assert result["a"] == pytest.approx(2.0)
        assert result["b"] == pytest.approx(4.0)

    def test_parallel_sum_at_prior(self):
        lump = _make_lump("parallel_sum", ["a", "b"], kind="Ceq", nominal=9.0)
        result = expand_lumped(lump, 9.0, atom_nominals=[3.0, 6.0])
        assert result["a"] == pytest.approx(3.0)
        assert result["b"] == pytest.approx(6.0)

    def test_chain_lump(self):
        from thermogram.solver.lumps import ChainAtoms
        lump = _make_lump("chain", ["r0", "r1", "c0", "c1"], kind="RC_chain", nominal=10.0, n=2)
        ca = ChainAtoms(r_atom_ids=["r0", "r1"], c_atom_ids=["c0", "c1"])
        result = expand_lumped(lump, (6.0, 4.0), chain_atoms=ca)
        assert result["r0"] == pytest.approx(3.0)
        assert result["r1"] == pytest.approx(3.0)
        assert result["c0"] == pytest.approx(2.0)
        assert result["c1"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# apply_atom_values
# ---------------------------------------------------------------------------

class TestApplyAtomValues:
    def _model(self):
        return {
            "nodes": [
                {"id": "r1", "kind": "resistance", "label": "R1", "R": 1.0},
                {"id": "m1", "kind": "mass", "label": "M1", "C": 1000.0},
                {"id": "b1", "kind": "boundary", "label": "B1", "T_source": "sig"},
            ],
            "edges": [],
        }

    def test_patch_resistance(self):
        m = apply_atom_values(self._model(), {"r1": 2.5})
        node = next(n for n in m["nodes"] if n["id"] == "r1")
        assert node["R"] == pytest.approx(2.5)

    def test_patch_mass(self):
        m = apply_atom_values(self._model(), {"m1": 5000.0})
        node = next(n for n in m["nodes"] if n["id"] == "m1")
        assert node["C"] == pytest.approx(5000.0)

    def test_original_unmodified(self):
        original = self._model()
        original_R = original["nodes"][0]["R"]
        apply_atom_values(original, {"r1": 99.0})
        assert original["nodes"][0]["R"] == pytest.approx(original_R)

    def test_missing_id_raises(self):
        with pytest.raises(ValueError, match="not found"):
            apply_atom_values(self._model(), {"nonexistent": 1.0})


# ---------------------------------------------------------------------------
# Prior composition
# ---------------------------------------------------------------------------

class TestPriorComposition:
    def test_series_prior_nominal_equals_sum(self):
        p = compose_series_prior([1.0, 2.0, 3.0])
        assert p.nominal == pytest.approx(6.0)

    def test_parallel_sum_prior(self):
        p = compose_parallel_sum_prior([100.0, 200.0])
        assert p.nominal == pytest.approx(300.0)

    def test_parallel_inv_prior(self):
        p = compose_parallel_inv_prior([2.0, 4.0])
        expected = 1.0 / (0.5 + 0.25)
        assert p.nominal == pytest.approx(expected)

    def test_chain_prior(self):
        pr, pc = compose_chain_prior(5.0, 1e6)
        assert pr.nominal == pytest.approx(5.0)
        assert pc.nominal == pytest.approx(1e6)
