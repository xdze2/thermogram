"""Tests for solver/assemble.py — Step 3a verification."""

import json
from pathlib import Path

import numpy as np
import pytest

from thermogram.solver.assemble import assemble

DATA = Path(__file__).parents[2] / "data" / "examples"


def load(name: str) -> dict:
    with open(DATA / name) as f:
        return json.load(f)


class TestChambre1R1C:
    def setup_method(self):
        self.sys = assemble(load("chambre_1r1c.json"))

    def test_shape(self):
        s = self.sys
        assert s.A.shape == (1, 1), f"expected (1,1), got {s.A.shape}"
        assert len(s.mass_ids) == 1
        assert len(s.boundary_ids) == 1
        assert len(s.source_ids) == 1

    def test_tau_matches_RC(self):
        """τ = -1/A[0,0] should equal R·C."""
        s = self.sys
        # chambre_1r1c: R=0.034, C=8_640_000
        R = 0.034
        C = 8_640_000
        tau_expected = R * C
        tau_computed = -1.0 / s.A[0, 0]
        assert abs(tau_computed - tau_expected) / tau_expected < 1e-9

    def test_B_boundary_nonzero(self):
        s = self.sys
        assert s.B_boundary.shape == (1, 1)
        assert s.B_boundary[0, 0] > 0

    def test_B_source_nonzero(self):
        s = self.sys
        assert s.B_source.shape == (1, 1)
        assert s.B_source[0, 0] > 0


class TestChambreV1:
    def setup_method(self):
        self.sys = assemble(load("chambre_v1.json"))

    def test_shape(self):
        s = self.sys
        assert s.A.shape == (2, 2), f"expected (2,2), got {s.A.shape}"
        assert len(s.mass_ids) == 2
        assert len(s.boundary_ids) == 1
        assert len(s.source_ids) == 2

    def test_mass_ids(self):
        s = self.sys
        assert set(s.mass_ids) == {"chambre", "mur_SE"}

    def test_eigenvalues_negative(self):
        """A must be stable: all eigenvalues negative."""
        s = self.sys
        eigs = np.linalg.eigvals(s.A).real
        assert np.all(eigs < 0), f"eigenvalues not all negative: {eigs}"

    def test_two_time_constants(self):
        """One fast (hours) and one slow (days) mode."""
        s = self.sys
        eigs = np.linalg.eigvals(s.A).real
        taus_h = sorted(-1.0 / e / 3600.0 for e in eigs)  # ascending: fast first
        tau_fast, tau_slow = taus_h
        assert tau_fast < 24.0, f"fast τ={tau_fast:.1f} h should be < 24 h"
        assert tau_slow > 24.0, f"slow τ={tau_slow:.1f} h should be > 24 h"

    def test_tau_slow_much_larger_than_tau_fast(self):
        """τ_slow should be well-separated from τ_fast (at least 5×).

        The simple hand estimate τ_slow ≈ C_mur × R_wall ignores parallel
        conduction paths, so it over-estimates. The important structural
        property is that the two modes are well-separated.
        """
        s = self.sys
        eigs = np.linalg.eigvals(s.A).real
        taus_h = sorted(-1.0 / e / 3600.0 for e in eigs)
        tau_fast, tau_slow = taus_h
        assert tau_slow / tau_fast > 5.0, (
            f"modes not well-separated: τ_fast={tau_fast:.1f} h, τ_slow={tau_slow:.1f} h"
        )

    def test_A_row_sum_zero_for_mass_mass(self):
        """Energy conservation: each row of A + matching column of B_boundary sums to ~0."""
        s = self.sys
        for i in range(len(s.mass_ids)):
            row_sum = s.A[i, :].sum() + s.B_boundary[i, :].sum()
            assert abs(row_sum) < 1e-10, (
                f"row {i} ({s.mass_ids[i]}) sum={row_sum:.2e}, expected 0"
            )
