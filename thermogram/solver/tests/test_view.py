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
# Human-readable lump labels (Step 4.2)
# ---------------------------------------------------------------------------

class TestLumpLabels:
    def setup_method(self):
        self.house = _load("maison_test.json")
        self.model, self.emap = expand(self.house)
        self.element_labels = {}
        for r in self.house.get("rooms", []):
            if r.get("label"):
                self.element_labels[r["id"]] = r["label"]
        for e in self.house.get("elements", []):
            if e.get("label"):
                self.element_labels[e["id"]] = e["label"]

    def test_element_labels_propagate(self):
        view = build_default_view(self.model, self.emap, self.element_labels)
        by_kind = {l.kind: l for l in view.lumped}
        # Every lump realizing a known element gets that element's label.
        for lump in view.lumped:
            if lump.realizes in self.element_labels:
                assert lump.label == self.element_labels[lump.realizes], (
                    f"{lump.kind} {lump.id}: label {lump.label!r} != "
                    f"{self.element_labels[lump.realizes]!r}"
                )
        # Concretely: the chained wall, the room, and the boundary are named.
        assert by_kind["RC_chain"].label == "Wall SE"
        assert by_kind["Ceq"].label == "Chambre"
        assert by_kind["T_boundary"].label == "Extérieur"

    def test_no_label_is_uuid_free_fallback(self):
        """Without element_labels, labels fall back to cleaned atom labels,
        never raw UUIDs."""
        view = build_default_view(self.model, self.emap)
        for lump in view.lumped:
            assert lump.label, f"{lump.id} has empty label"
            # cleaned atom labels strip the (Rsi)/[inner] provenance suffixes
            assert "(" not in lump.label and "[" not in lump.label, lump.label


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


# ---------------------------------------------------------------------------
# Parallel resistance paths between the same node pair merge into one Req.
#
# Several no-mass walls + a window bridging the same room↔outdoor pair are
# physically in parallel: only their summed conductance is identifiable from
# the indoor temperature. The default view must collapse them into a single
# parallel_inv_sum Req, not leave one Req per element (which is structurally
# unidentifiable and wrecks the fit).
# ---------------------------------------------------------------------------

class TestParallelPathsMerge:
    ROOM = "a1b2c3d4-0001-0000-0000-000000000001"
    OUT = "a1b2c3d4-0001-0000-0000-000000000002"

    def _house(self) -> dict:
        return {
            "schema_version": "0.3",
            "name": "parallel_test",
            "rooms": [{
                "id": self.ROOM, "label": "Chambre", "role": "mass",
                "a": 5, "b": 5, "c": 3,
            }],
            "materials": {
                "brick": {"lambda": 0.8, "rho": 1800, "cp": 840},
            },
            "elements": [
                {"id": self.OUT, "kind": "outdoor", "label": "Extérieur"},
                {
                    "id": "a1b2c3d4-0001-0000-0000-000000000010",
                    "kind": "opaque", "label": "Wall NE",
                    "between": [self.ROOM, self.OUT], "a": 4, "b": 2.5,
                    "no_mass": True,
                    "layers": [{"material": "brick", "thickness": 0.20}],
                },
                {
                    "id": "a1b2c3d4-0001-0000-0000-000000000011",
                    "kind": "opaque", "label": "Wall N",
                    "between": [self.ROOM, self.OUT], "a": 3, "b": 2.5,
                    "no_mass": True,
                    "layers": [{"material": "brick", "thickness": 0.20}],
                },
                {
                    "id": "a1b2c3d4-0001-0000-0000-000000000012",
                    "kind": "glazing", "label": "win",
                    "between": [self.ROOM, self.OUT], "a": 1.2, "b": 1.0,
                    "U": 2.8,
                },
            ],
        }

    def setup_method(self):
        house = self._house()
        self.model, self.emap = expand(house)
        labels = {self.ROOM: "Chambre", self.OUT: "Extérieur"}
        for e in house["elements"]:
            labels[e["id"]] = e["label"]
        self.view = build_default_view(self.model, self.emap, labels)

    def test_single_merged_req(self):
        reqs = [l for l in self.view.lumped if l.kind == "Req"]
        assert len(reqs) == 1, (
            f"Expected the 2 no-mass walls + window to merge into 1 Req, "
            f"got {len(reqs)}: {[l.label for l in reqs]}"
        )

    def test_merged_req_is_parallel_inv_sum(self):
        req = next(l for l in self.view.lumped if l.kind == "Req")
        assert req.combine == "parallel_inv_sum"
        assert len(req.atoms) == 3

    def test_merged_req_terminals(self):
        req = next(l for l in self.view.lumped if l.kind == "Req")
        assert {req.node_a, req.node_b} == {"Chambre", "Extérieur"}

    def test_merged_label_lists_all_elements(self):
        req = next(l for l in self.view.lumped if l.kind == "Req")
        for name in ("Wall NE", "Wall N", "win"):
            assert name in (req.label or ""), req.label

    def test_merged_prior_equals_parallel_sum(self):
        """The merged Req nominal is the parallel combination of the atom R's:
        1 / Σ(1/R_i). This makes φ == prior reproduce the original conductance."""
        req = next(l for l in self.view.lumped if l.kind == "Req")
        nodes = {n["id"]: n for n in self.model["nodes"]}
        r_atoms = [nodes[a]["R"] for a in req.atoms]
        expected = 1.0 / sum(1.0 / r for r in r_atoms)
        assert req.prior.nominal == pytest.approx(expected)
