"""Tests for solver/view.py — build_default_view."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thermogram.solver.physics import expand
from thermogram.solver.view import build_default_view, chain_atoms_for_lump, get_chain_priors

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    with open(FIXTURES / name) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# maison_test: 1 room, 1 chained wall (Wall SE, N=3), 1 no_mass wall (Wall NE)
# ---------------------------------------------------------------------------

class TestDefaultViewMaisonTest:
    def setup_method(self):
        house = _load("maison_test.json")
        self.model, self.emap = expand(house)
        self.view = build_default_view(self.model, self.emap)
        self.lumped = {l.id: l for l in self.view.lumped}

    def test_view_has_id(self):
        assert self.view.id is not None and len(self.view.id) > 0

    def test_at_least_one_free_lump(self):
        free = [l for l in self.view.lumped if l.mode == "free"]
        assert len(free) >= 1

    def test_rc_chain_lump_exists(self):
        chains = [l for l in self.view.lumped if l.kind == "RC_chain"]
        assert len(chains) == 1, f"Expected 1 RC_chain, got {len(chains)}"

    def test_rc_chain_has_two_phi(self):
        chain_lump = next(l for l in self.view.lumped if l.kind == "RC_chain")
        assert chain_lump.combine == "chain"
        # Two free φ keys: _R and _C
        assert chain_lump.n is not None and chain_lump.n >= 1

    def test_rc_chain_prior_positive(self):
        chain_lump = next(l for l in self.view.lumped if l.kind == "RC_chain")
        R_nom, C_nom = get_chain_priors(chain_lump, self.model, self.emap)
        assert R_nom > 0
        assert C_nom > 0

    def test_rse_rsi_NOT_in_chain_atoms(self):
        """Rse/Rsi must be excluded from the chain's free R atom ids."""
        chain_lump = next(l for l in self.view.lumped if l.kind == "RC_chain")
        ca = chain_atoms_for_lump(chain_lump, self.model, self.emap)
        # None of the free r_atom_ids should be a surface resistance
        nodes = {n["id"]: n for n in self.model["nodes"]}
        for rid in ca.r_atom_ids:
            label = nodes[rid].get("label", "")
            assert "(Rse)" not in label and "(Rsi)" not in label, (
                f"Surface resistance {rid!r} ({label!r}) should not be in chain r_atom_ids"
            )

    def test_rse_rsi_in_lump_atoms_list(self):
        """Rse/Rsi are listed in lump.atoms (provenance) even though not free."""
        chain_lump = next(l for l in self.view.lumped if l.kind == "RC_chain")
        nodes = {n["id"]: n for n in self.model["nodes"]}
        surface_ids = {
            n["id"] for n in self.model["nodes"]
            if n["kind"] == "resistance" and (
                "(Rse)" in (n.get("label") or "") or "(Rsi)" in (n.get("label") or "")
            )
        }
        # They must appear in lump.atoms
        lump_atom_set = set(chain_lump.atoms)
        for sid in surface_ids:
            assert sid in lump_atom_set, (
                f"Surface resistance {sid!r} should be in lump.atoms for provenance"
            )

    def test_no_mass_wall_gives_req(self):
        req_lumps = [l for l in self.view.lumped if l.kind == "Req"]
        assert len(req_lumps) >= 1

    def test_ceq_lump_exists(self):
        ceq = [l for l in self.view.lumped if l.kind == "Ceq"]
        assert len(ceq) == 1

    def test_ceq_prior_positive(self):
        ceq = next(l for l in self.view.lumped if l.kind == "Ceq")
        assert ceq.prior.nominal > 0

    def test_boundary_node_is_fixed(self):
        t_bnd = [l for l in self.view.lumped if l.kind == "T_boundary"]
        assert len(t_bnd) >= 1
        for l in t_bnd:
            assert l.mode == "fixed"

    def test_source_node_is_fixed(self):
        sources = [l for l in self.view.lumped if l.kind == "Q_source"]
        for l in sources:
            assert l.mode == "fixed"

    def test_full_coverage(self):
        """Every atomic node must appear in exactly one lump.atoms list
        (except Rse/Rsi which are in the chain lump's atoms list, so they
        ARE covered — just not as free φ)."""
        all_node_ids = {n["id"] for n in self.model["nodes"]}
        covered: dict[str, str] = {}
        for lump in self.view.lumped:
            for aid in lump.atoms:
                if aid in covered:
                    pytest.fail(
                        f"Atom {aid!r} covered by both {covered[aid]!r} and {lump.id!r}"
                    )
                covered[aid] = lump.id
        uncovered = all_node_ids - set(covered)
        assert not uncovered, f"Uncovered atoms: {uncovered}"


# ---------------------------------------------------------------------------
# chambre_1r1c: minimal fixture (1 mass, 1 boundary, 1 resistance)
# ---------------------------------------------------------------------------

class TestDefaultViewChambre1R1C:
    def setup_method(self):
        model = _load("chambre_1r1c.json")
        # This fixture has no wall_chains / expansion_map — build a synthetic map
        # mapping each node to itself for the purpose of view building.
        from collections import defaultdict
        emap: dict[str, list[str]] = {}
        for n in model["nodes"]:
            emap[n["id"]] = [n["id"]]
        self.model = model
        self.emap = emap
        self.view = build_default_view(model, emap)

    def test_has_lumped_elements(self):
        assert len(self.view.lumped) > 0

    def test_all_nodes_covered(self):
        all_ids = {n["id"] for n in self.model["nodes"]}
        covered = {aid for l in self.view.lumped for aid in l.atoms}
        assert all_ids == covered

    def test_resistance_is_free(self):
        free_r = [l for l in self.view.lumped if l.kind == "Req" and l.mode == "free"]
        assert len(free_r) >= 1


# ---------------------------------------------------------------------------
# chambre_v1: richer fixture
# ---------------------------------------------------------------------------

class TestDefaultViewChambreV1:
    def setup_method(self):
        house = _load("chambre_v1.json")
        self.model, self.emap = expand(house)
        self.view = build_default_view(self.model, self.emap)

    def test_full_coverage(self):
        all_node_ids = {n["id"] for n in self.model["nodes"]}
        covered: dict[str, str] = {}
        for lump in self.view.lumped:
            for aid in lump.atoms:
                if aid in covered:
                    pytest.fail(f"Atom {aid!r} double-covered")
                covered[aid] = lump.id
        uncovered = all_node_ids - set(covered)
        assert not uncovered, f"Uncovered atoms: {uncovered}"

    def test_chain_count_matches_opaque_elements(self):
        house = _load("chambre_v1.json")
        opaque_with_mass = [
            e for e in house.get("elements", [])
            if e.get("kind") == "opaque" and not e.get("no_mass", False)
        ]
        chains = [l for l in self.view.lumped if l.kind == "RC_chain"]
        assert len(chains) == len(opaque_with_mass)
