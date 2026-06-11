"""Tests for solver/physics.py — expand(house)."""

import json
from pathlib import Path

import pytest

from thermogram.solver.physics import expand, model_hash
from thermogram.solver.assemble import assemble

DATA = Path(__file__).parents[3] / "data"

with open(DATA / "houses" / "maison_test.json") as f:
    HOUSE = json.load(f)

# Convenience: UUIDs from maison_test.json
ROOM_CHAMBRE  = "a1b2c3d4-0001-0000-0000-000000000001"
OUTDOOR       = "a1b2c3d4-0001-0000-0000-000000000002"
OPAQUE_MUR_SE = "a1b2c3d4-0001-0000-0000-000000000004"


class TestExpandMaisonTest:
    def setup_method(self):
        self.model, self.emap = expand(HOUSE)

    def test_schema_version(self):
        assert self.model["schema_version"] == "0.3"

    def _zone_node_id(self, uuid: str) -> str:
        return f"z_{uuid.replace('-', '')}"

    def test_chambre_is_mass(self):
        """Room with role='mass' should produce a mass node."""
        kinds = {n["id"]: n["kind"] for n in self.model["nodes"]}
        chambre_node = self._zone_node_id(ROOM_CHAMBRE)
        assert chambre_node in kinds
        assert kinds[chambre_node] == "mass"

    def test_outdoor_is_boundary(self):
        kinds = {n["id"]: n["kind"] for n in self.model["nodes"]}
        outdoor_node = self._zone_node_id(OUTDOOR)
        assert outdoor_node in kinds
        assert kinds[outdoor_node] == "boundary"

    def test_expansion_map_chambre(self):
        assert ROOM_CHAMBRE in self.emap
        assert len(self.emap[ROOM_CHAMBRE]) >= 1

    def test_expansion_map_outdoor(self):
        assert OUTDOOR in self.emap

    def test_expansion_map_elements_present(self):
        assert OPAQUE_MUR_SE in self.emap

    def test_assembles_without_error(self):
        sys = assemble(self.model)
        assert sys.A.shape[0] >= 1

    def test_mass_node_count(self):
        sys = assemble(self.model)
        # chambre + wall lump nodes (chain_n >= 1 for brick_full 0.3m)
        assert len(sys.mass_ids) >= 1
        assert "z_a1b2c3d4000100000000000000000001" in sys.mass_ids

    def test_A_stable(self):
        import numpy as np
        sys = assemble(self.model)
        eigs = np.linalg.eigvals(sys.A).real
        assert all(e < 0 for e in eigs)

    def test_energy_conservation(self):
        """Each row of A + matching B_boundary row must sum to ~0."""
        import numpy as np
        sys = assemble(self.model)
        for i in range(len(sys.mass_ids)):
            row_sum = sys.A[i, :].sum() + sys.B_boundary[i, :].sum()
            assert abs(row_sum) < 1e-8, f"row {i} energy imbalance: {row_sum:.2e}"

    def test_solar_source_present(self):
        outdoor_elem = next(e for e in HOUSE["elements"] if e["id"] == OUTDOOR)
        solar_signal = outdoor_elem.get("solar_signal")
        source_nodes = [n for n in self.model["nodes"] if n["kind"] == "source"]
        assert any(n["signal"] == solar_signal for n in source_nodes)

    def test_opaque_wall_solar_source_gain(self):
        """Wall solar source gain = alpha * area, injected into outer surface node."""
        wall_elem = next(e for e in HOUSE["elements"] if e["id"] == OPAQUE_MUR_SE)
        alpha = wall_elem["solar_absorptance"]
        area = wall_elem["a"] * wall_elem["b"]
        expected_gain = alpha * area
        source_nodes = [n for n in self.model["nodes"] if n["kind"] == "source"]
        wall_solar = next((n for n in source_nodes if abs(n["gain"] - expected_gain) < 1e-9), None)
        assert wall_solar is not None

    def test_opaque_wall_solar_connected_to_m0(self):
        """Solar source must be connected to the outer surface mass node (m_0)."""
        wall_elem = next(e for e in HOUSE["elements"] if e["id"] == OPAQUE_MUR_SE)
        alpha = wall_elem["solar_absorptance"]
        area = wall_elem["a"] * wall_elem["b"]
        expected_gain = alpha * area
        source_nodes = [n for n in self.model["nodes"] if n["kind"] == "source"]
        solar_id = next(n["id"] for n in source_nodes if abs(n["gain"] - expected_gain) < 1e-9)
        # The edge from the solar source must reach a mass node (m_0)
        targets = {e["to"] for e in self.model["edges"] if e["from"] == solar_id}
        target_kinds = {n["kind"] for n in self.model["nodes"] if n["id"] in targets}
        assert target_kinds == {"mass"}

    def test_obs_signal_on_boundary(self):
        outdoor_node = self._zone_node_id(OUTDOOR)
        node = next(n for n in self.model["nodes"] if n["id"] == outdoor_node)
        outdoor_elem = next(e for e in HOUSE["elements"] if e["id"] == OUTDOOR)
        assert node["T_source"] == outdoor_elem["obs_signal"]


class TestExpandRoles:
    """Verify that room role field controls node type."""

    HOUSE_ROLES = {
        "schema_version": "0.3",
        "label": "Roles test",
        "materials": {
            "brick": {"lambda": 0.8, "rho": 1800, "cp": 840}
        },
        "rooms": [
            {"id": "r_mass",     "label": "Mass room",     "role": "mass",     "a": 4, "b": 4, "c": 2.5},
            {"id": "r_boundary", "label": "Boundary room", "role": "boundary", "a": 3, "b": 4, "c": 2.5,
             "obs_signal": "some/signal"},
            {"id": "r_fixed",    "label": "Fixed room",    "role": "fixed",    "a": 3, "b": 3, "c": 2.5,
             "T_fixed": 18.0},
        ],
        "elements": [
            {"id": "out1", "kind": "outdoor", "label": "Ext",
             "obs_signal": "open_meteo_historic/temperature_2m?location=home"},
            {"id": "w1", "kind": "opaque", "label": "Wall mass-ext",
             "between": ["r_mass", "out1"], "a": 4.0, "b": 2.5,
             "layers": [{"material": "brick", "thickness": 0.2}]},
            {"id": "w2", "kind": "opaque", "label": "Wall mass-boundary",
             "between": ["r_mass", "r_boundary"], "a": 3.0, "b": 2.5,
             "layers": [{"material": "brick", "thickness": 0.2}]},
            {"id": "w3", "kind": "opaque", "label": "Wall mass-fixed",
             "between": ["r_mass", "r_fixed"], "a": 3.0, "b": 2.5,
             "layers": [{"material": "brick", "thickness": 0.2}]},
        ],
    }

    def test_mass_room_is_mass(self):
        model, _ = expand(self.HOUSE_ROLES)
        kinds = {n["id"]: n["kind"] for n in model["nodes"]}
        assert kinds["z_r_mass"] == "mass"

    def test_boundary_room_is_boundary(self):
        model, _ = expand(self.HOUSE_ROLES)
        kinds = {n["id"]: n["kind"] for n in model["nodes"]}
        assert kinds["z_r_boundary"] == "boundary"

    def test_boundary_room_t_source_is_signal(self):
        model, _ = expand(self.HOUSE_ROLES)
        node = next(n for n in model["nodes"] if n["id"] == "z_r_boundary")
        assert node["T_source"] == "some/signal"

    def test_fixed_room_is_boundary(self):
        model, _ = expand(self.HOUSE_ROLES)
        kinds = {n["id"]: n["kind"] for n in model["nodes"]}
        assert kinds["z_r_fixed"] == "boundary"

    def test_fixed_room_t_source_is_constant(self):
        model, _ = expand(self.HOUSE_ROLES)
        node = next(n for n in model["nodes"] if n["id"] == "z_r_fixed")
        assert node["T_source"] == 18.0

    def test_only_one_room_mass_node(self):
        model, _ = expand(self.HOUSE_ROLES)
        sys = assemble(model)
        # r_mass room + wall lump nodes
        assert "z_r_mass" in sys.mass_ids

    def test_energy_conservation(self):
        import numpy as np
        model, _ = expand(self.HOUSE_ROLES)
        sys = assemble(model)
        for i in range(len(sys.mass_ids)):
            row_sum = sys.A[i, :].sum() + sys.B_boundary[i, :].sum()
            assert abs(row_sum) < 1e-8, f"row {i} energy imbalance: {row_sum:.2e}"


class TestExpandTwoRooms:
    """House with two mass rooms: both wired together via a shared wall."""

    HOUSE_2R = {
        "schema_version": "0.3",
        "label": "Two rooms",
        "materials": {
            "brick": {"lambda": 0.8, "rho": 1800, "cp": 840}
        },
        "rooms": [
            {"id": "r1", "label": "Room1", "role": "mass", "a": 4, "b": 4, "c": 2.5},
            {"id": "r2", "label": "Room2", "role": "mass", "a": 3, "b": 4, "c": 2.5},
        ],
        "elements": [
            {"id": "out1", "kind": "outdoor", "label": "Ext",
             "obs_signal": "open_meteo_historic/temperature_2m?location=home"},
            {"id": "wall_shared", "kind": "opaque", "label": "Shared wall",
             "between": ["r1", "r2"], "a": 4.0, "b": 2.5,
             "layers": [{"material": "brick", "thickness": 0.2}]},
            {"id": "wall_ext", "kind": "opaque", "label": "Ext wall",
             "between": ["r1", "out1"], "a": 4.0, "b": 2.5,
             "layers": [{"material": "brick", "thickness": 0.3}]},
        ],
    }

    def test_both_rooms_give_two_masses(self):
        model, emap = expand(self.HOUSE_2R)
        sys = assemble(model)
        # Both room nodes present; wall lump nodes also contribute
        assert "z_r1" in sys.mass_ids
        assert "z_r2" in sys.mass_ids

    def test_shared_wall_in_emap(self):
        _, emap = expand(self.HOUSE_2R)
        assert "wall_shared" in emap

    def test_energy_conservation_two_rooms(self):
        import numpy as np
        model, _ = expand(self.HOUSE_2R)
        sys = assemble(model)
        for i in range(len(sys.mass_ids)):
            row_sum = sys.A[i, :].sum() + sys.B_boundary[i, :].sum()
            assert abs(row_sum) < 1e-8, f"row {i} energy imbalance: {row_sum:.2e}"


class TestModelHash:
    def test_hash_is_12_chars(self):
        elements = [{"id": "e1", "kind": "opaque"}]
        h = model_hash(elements)
        assert len(h) == 12

    def test_hash_deterministic(self):
        elements = [{"id": "e1", "kind": "opaque"}, {"b": 2, "a": 1}]
        assert model_hash(elements) == model_hash(elements)

    def test_hash_changes_on_modification(self):
        e1 = [{"id": "e1", "R": 1.0}]
        e2 = [{"id": "e1", "R": 2.0}]
        assert model_hash(e1) != model_hash(e2)
