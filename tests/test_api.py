"""
D3 acceptance tests for the FastAPI backend.

The signal-grouping model is now live:
- Modules are DERIVED from element boundaries (no POST/DELETE /modules,
  no PUT .../routing).
- GET /document returns derived modules + derived signals.
- GET /assembly gains required_signals; ownership/parameters/graph/problems kept.
- The caravan is authored via element CRUD only.

Tests:
1. Author the caravan via element CRUD; /document shows derived modules + signals.
2. /assembly.required_signals lists exactly {T_ext, G_sol_S} for the caravan.
3. Module CRUD/routing endpoints return 404/405 (retired).
4. GET /assembly never 500s (assembly problems → problems[] list).
5. POST /simulate on the caravan returns a non-constant, settling T_room.
6. GET /identifiability returns valid statuses.
7. GET /topology.svg returns an SVG image.
8. HeatSource with signal= produces a prescribed signal.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from thnodes.api.app import app
from thnodes.api.store import _store
from thnodes.api.models import RoomDoc


VALID_STATUSES = {"resolvable", "borderline", "prior_dominated"}


@pytest.fixture(autouse=True)
def reset_store():
    """Reset session store before each test so tests are independent."""
    _store.clear()
    _store["default"] = RoomDoc()
    yield
    _store.clear()
    _store["default"] = RoomDoc()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ── helpers ────────────────────────────────────────────────────────────────────

BASE = "/api/models/default"

LIGHT_WALL_FIELDS = {
    "area": 10.0,
    "orientation": "S",
    "layers": [{"material": "insulation_mineral_wool", "thickness": 0.1}],
    "alpha": 0.6,
    "treatment": "",   # forced simple_loss for light wall
}

WINDOW_FIELDS = {
    "area": 4.0,
    "orientation": "S",
    "U": 1.2,
    "shgc": 0.6,
}

INDOOR_MASS_FIELDS = {
    "a": 5.0,
    "b": 4.0,
    "c": 2.5,
    "furniture": "normal",
}


def _add_element(client, type_: str, fields: dict) -> str:
    r = client.post(f"{BASE}/elements", json={"type": type_, "fields": fields})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _build_caravan(client) -> tuple[str, str, str]:
    """
    Build the caravan via element CRUD only: IndoorMass + OuterWall (light, S) + Window (S).
    Returns (im_eid, wall_eid, win_eid).
    The grouping rule derives: RoomMass, DirectLoss[T_ext], SolarGain[G_sol_S].
    """
    im_eid = _add_element(client, "IndoorMass", INDOOR_MASS_FIELDS)
    wall_eid = _add_element(client, "OuterWall", LIGHT_WALL_FIELDS)
    win_eid = _add_element(client, "Window", WINDOW_FIELDS)
    return im_eid, wall_eid, win_eid


# ── registry ───────────────────────────────────────────────────────────────────

def test_registry(client):
    r = client.get("/api/registry")
    assert r.status_code == 200
    data = r.json()
    type_names = {et["type_name"] for et in data["element_types"]}
    assert "OuterWall" in type_names
    assert "Window" in type_names
    mod_names = {mt["type_name"] for mt in data["module_types"]}
    assert "RoomMass" in mod_names
    assert "DirectLoss" in mod_names
    assert "fields" in data["layer_schema"]


# ── document CRUD ──────────────────────────────────────────────────────────────

def test_document_empty(client):
    r = client.get(f"{BASE}/document")
    assert r.status_code == 200
    data = r.json()
    assert data["model_id"] == "default"
    assert data["elements"] == []
    # Empty model: no elements → no derived modules, no signals.
    assert data["modules"] == []
    assert data["signals"] == []


def test_add_element_and_delete(client):
    eid = _add_element(client, "OuterWall", LIGHT_WALL_FIELDS)
    r = client.get(f"{BASE}/document")
    assert any(e["id"] == eid for e in r.json()["elements"])

    r = client.delete(f"{BASE}/elements/{eid}")
    assert r.status_code == 204

    r = client.get(f"{BASE}/document")
    assert all(e["id"] != eid for e in r.json()["elements"])


def test_patch_element(client):
    eid = _add_element(client, "OuterWall", LIGHT_WALL_FIELDS)
    r = client.patch(f"{BASE}/elements/{eid}", json={"fields": {"area": 15.0}})
    assert r.status_code == 200
    assert r.json()["fields"]["area"] == 15.0


def test_element_budgets_non_null(client):
    eid = _add_element(client, "Window", WINDOW_FIELDS)
    r = client.get(f"{BASE}/document")
    elem = next(e for e in r.json()["elements"] if e["id"] == eid)
    assert elem["budgets"]["CONDUCTION"]["UA"] == pytest.approx(1.2 * 4.0, rel=1e-4)
    assert elem["budgets"]["SOLAR_TRANSMISSION"]["shgcA"] == pytest.approx(0.6 * 4.0, rel=1e-4)


def test_unknown_model_404(client):
    r = client.get("/api/models/nonexistent/document")
    assert r.status_code == 404


# ── D3: derived modules in /document ─────────────────────────────────────────

def test_document_derived_modules_caravan(client):
    """
    Author the caravan via element CRUD; /document shows derived modules.
    Expected: RoomMass, DirectLoss[T_ext], SolarGain[G_sol_S].
    """
    im_eid, wall_eid, win_eid = _build_caravan(client)

    r = client.get(f"{BASE}/document")
    assert r.status_code == 200
    data = r.json()

    module_ids = {m["id"] for m in data["modules"]}
    assert "RoomMass" in module_ids
    assert "DirectLoss[T_ext]" in module_ids
    assert "SolarGain[G_sol_S]" in module_ids

    # DirectLoss[T_ext] claims both wall and window (both contribute CONDUCTION).
    dl = next(m for m in data["modules"] if m["id"] == "DirectLoss[T_ext]")
    assert wall_eid in dl["element_ids"]
    assert win_eid in dl["element_ids"]

    # SolarGain[G_sol_S] claims the window only.
    sg = next(m for m in data["modules"] if m["id"] == "SolarGain[G_sol_S]")
    assert win_eid in sg["element_ids"]
    assert wall_eid not in sg["element_ids"]


def test_document_derived_signals_caravan(client):
    """
    After authoring the caravan, /document.signals lists T_ext and G_sol_S.
    """
    _build_caravan(client)

    r = client.get(f"{BASE}/document")
    assert r.status_code == 200
    signal_names = {s["name"] for s in r.json()["signals"]}
    assert "T_ext" in signal_names
    assert "G_sol_S" in signal_names


def test_document_modules_have_correct_shape(client):
    """Each derived module entry has id, type, signal, element_ids."""
    _build_caravan(client)

    r = client.get(f"{BASE}/document")
    for m in r.json()["modules"]:
        assert "id" in m
        assert "type" in m
        assert "signal" in m
        assert "element_ids" in m
        assert isinstance(m["element_ids"], list)


def test_document_module_gc_after_element_delete(client):
    """
    Deleting the only Window in a caravan GCs G_sol_S signal and
    removes SolarGain[G_sol_S] from derived modules.
    """
    im_eid, wall_eid, win_eid = _build_caravan(client)

    # Before delete: SolarGain[G_sol_S] exists.
    r = client.get(f"{BASE}/document")
    module_ids = {m["id"] for m in r.json()["modules"]}
    assert "SolarGain[G_sol_S]" in module_ids
    signal_names = {s["name"] for s in r.json()["signals"]}
    assert "G_sol_S" in signal_names

    # Delete the window.
    client.delete(f"{BASE}/elements/{win_eid}")

    # After delete: SolarGain[G_sol_S] gone; G_sol_S signal GC'd.
    r = client.get(f"{BASE}/document")
    module_ids = {m["id"] for m in r.json()["modules"]}
    assert "SolarGain[G_sol_S]" not in module_ids
    signal_names = {s["name"] for s in r.json()["signals"]}
    assert "G_sol_S" not in signal_names


# ── D3: retired endpoints ────────────────────────────────────────────────────

def test_post_modules_endpoint_retired(client):
    """POST /modules returns 404/405 — endpoint retired in D3."""
    r = client.post(f"{BASE}/modules", json={"type": "DirectLoss", "fields": {}})
    assert r.status_code in (404, 405), (
        f"Expected 404/405 for retired endpoint; got {r.status_code}: {r.text}"
    )


def test_delete_module_endpoint_retired(client):
    """DELETE /modules/{mid} returns 404/405 — endpoint retired in D3."""
    r = client.delete(f"{BASE}/modules/m0")
    assert r.status_code in (404, 405), (
        f"Expected 404/405 for retired endpoint; got {r.status_code}: {r.text}"
    )


def test_put_routing_endpoint_retired(client):
    """PUT /modules/{mid}/routing returns 404/405 — endpoint retired in D3."""
    r = client.put(f"{BASE}/modules/m0/routing", json={"element_ids": []})
    assert r.status_code in (404, 405), (
        f"Expected 404/405 for retired endpoint; got {r.status_code}: {r.text}"
    )


# ── assembly: caravan valid ────────────────────────────────────────────────────

def test_assembly_caravan_no_problems(client):
    """
    Caravan assembled correctly — ownership/parameters/states present,
    problems is empty, required_signals lists T_ext and G_sol_S.
    """
    im_eid, wall_eid, win_eid = _build_caravan(client)

    r = client.get(f"{BASE}/assembly")
    assert r.status_code == 200
    data = r.json()

    assert data["problems"] == [], data["problems"]
    assert "T_room" in data["states"]
    # signal_names from System (ODE-level) — T_ext, G_sol_S, _T_sol_air may vary.
    # Check required_signals shape.
    req_names = {s["name"] for s in data["required_signals"]}
    assert "T_ext" in req_names
    assert "G_sol_S" in req_names

    param_names = {p["name"] for p in data["parameters"]}
    assert "H_ve" in param_names
    assert "C_room" in param_names

    # Ownership: CONDUCTION on wall -> DirectLoss[T_ext]
    channels_owned = {(o["element_id"], o["channel"]) for o in data["ownership"]}
    assert (wall_eid, "CONDUCTION") in channels_owned
    assert (win_eid, "SOLAR_TRANSMISSION") in channels_owned


def test_assembly_required_signals_caravan(client):
    """
    D3 acceptance: /assembly.required_signals lists exactly T_ext and G_sol_S
    for the caravan.
    """
    _build_caravan(client)

    r = client.get(f"{BASE}/assembly")
    assert r.status_code == 200
    data = r.json()

    req = data["required_signals"]
    req_names = {s["name"] for s in req}
    assert req_names == {"T_ext", "G_sol_S"}

    # Each signal has the correct shape.
    for sig in req:
        assert "id" in sig
        assert "name" in sig
        assert "kind" in sig
        assert "role" in sig
        assert "meta" in sig

    t_ext = next(s for s in req if s["name"] == "T_ext")
    assert t_ext["role"] == "exterior"
    assert t_ext["kind"] == "temperature"

    g_sol = next(s for s in req if s["name"] == "G_sol_S")
    assert g_sol["role"] == "solar"
    assert g_sol["kind"] == "irradiance"
    assert g_sol["meta"]["orientation"] == "S"


def test_assembly_module_id_stable(client):
    """Derived module IDs in /assembly are stable string keys like 'DirectLoss[T_ext]'."""
    _build_caravan(client)

    r = client.get(f"{BASE}/assembly")
    assert r.status_code == 200
    param_module_ids = {p["module_id"] for p in r.json()["parameters"]}
    # DirectLoss[T_ext] owns H_ve; RoomMass owns C_room; SolarGain[G_sol_S] owns shgcA.
    assert "DirectLoss[T_ext]" in param_module_ids
    assert "RoomMass" in param_module_ids
    assert "SolarGain[G_sol_S]" in param_module_ids


def test_assembly_graph_nodes_and_edges(client):
    _build_caravan(client)
    r = client.get(f"{BASE}/assembly")
    data = r.json()

    node_ids = {n["id"] for n in data["graph"]["nodes"]}
    assert "T_room" in node_ids
    assert "T_ext" in node_ids
    assert "G_sol_S" in node_ids

    # At least one edge points to T_room
    assert any(e["to"] == "T_room" for e in data["graph"]["edges"])


def test_assembly_parameter_contributions(client):
    im_eid, wall_eid, win_eid = _build_caravan(client)
    r = client.get(f"{BASE}/assembly")
    data = r.json()

    h_ve = next(p for p in data["parameters"] if p["name"] == "H_ve")
    assert len(h_ve["contributions"]) > 0
    contrib_eids = {c["element_id"] for c in h_ve["contributions"]}
    # Wall and window both contribute CONDUCTION -> H_ve
    assert wall_eid in contrib_eids or win_eid in contrib_eids


# ── assembly: missing room mass ────────────────────────────────────────────────

def test_assembly_missing_room_mass(client):
    """Assembly with no IndoorMass returns problems but no 500."""
    _add_element(client, "Window", WINDOW_FIELDS)
    r = client.get(f"{BASE}/assembly")
    assert r.status_code == 200
    data = r.json()
    kinds = [p["kind"] for p in data["problems"]]
    assert "missing_room_mass" in kinds
    # required_signals still populated even with problems.
    assert "required_signals" in data


# ── simulate ───────────────────────────────────────────────────────────────────

def test_simulate_caravan_settling(client):
    """
    Simulate the caravan — T_room is non-constant and settles toward
    a warmer equilibrium when T_ext > initial T_room.
    """
    _build_caravan(client)

    n = 48  # 48 hours
    T_ext = [20.0] * n   # constant warm exterior
    G_sol_S = [0.0] * n

    body = {
        "signals": {"T_ext": T_ext, "G_sol_S": G_sol_S},
        "x0": [15.0],       # cold start
        "dt": 3600.0,
    }
    r = client.post(f"{BASE}/simulate", json=body)
    assert r.status_code == 200, r.text
    data = r.json()

    t_room = data["states"]["T_room"]
    assert len(t_room) == n
    # Non-constant
    assert max(t_room) - min(t_room) > 0.1
    # Monotonically warming (starts cold, warms to T_ext)
    assert t_room[-1] > t_room[0]
    # Should approach T_ext from below after 48h
    assert t_room[-1] < 20.5  # doesn't overshoot
    assert t_room[-1] > 18.0  # has warmed significantly


def test_simulate_missing_room_mass_400(client):
    """Simulate on an incomplete room returns 400, not 500."""
    _add_element(client, "Window", WINDOW_FIELDS)
    body = {
        "signals": {"T_ext": [20.0] * 5, "G_sol_S": [0.0] * 5},
        "dt": 3600.0,
    }
    r = client.post(f"{BASE}/simulate", json=body)
    assert r.status_code == 400


# ── identifiability ────────────────────────────────────────────────────────────

def test_identifiability_caravan(client):
    """
    GET /identifiability returns a param_status dict with all param names
    and valid status values.
    """
    _build_caravan(client)

    r = client.get(f"{BASE}/identifiability")
    assert r.status_code == 200, r.text
    data = r.json()

    assert "param_status" in data
    ps = data["param_status"]
    assert set(ps.keys()) >= {"H_ve", "C_room"}

    for pname, info in ps.items():
        assert info["status"] in VALID_STATUSES, f"{pname}: {info['status']}"
        assert "reason" in info


def test_identifiability_missing_room_mass_400(client):
    r = client.get(f"{BASE}/identifiability")
    assert r.status_code == 400


# ── topology ───────────────────────────────────────────────────────────────────

def test_topology_returns_image(client):
    _build_caravan(client)
    r = client.get(f"{BASE}/topology.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert len(r.content) > 100  # non-trivial SVG


def test_topology_incomplete_room_400(client):
    r = client.get(f"{BASE}/topology.svg")
    assert r.status_code == 400


# ── HeatSource with signal field ──────────────────────────────────────────────

def test_heatsource_signal_produces_prescribed_signal(client):
    """
    A HeatSource with signal="hvac" produces a prescribed signal Q_hvac in
    /document.signals and a SourceFlux[Q_hvac] module in /document.modules.
    """
    _add_element(client, "IndoorMass", INDOOR_MASS_FIELDS)
    _add_element(client, "HeatSource", {"area": 0.0, "signal": "hvac"})

    r = client.get(f"{BASE}/document")
    assert r.status_code == 200
    data = r.json()

    signal_names = {s["name"] for s in data["signals"]}
    assert "Q_hvac" in signal_names

    presc = next(s for s in data["signals"] if s["name"] == "Q_hvac")
    assert presc["kind"] == "flux"
    assert presc["role"] == "prescribed"

    module_ids = {m["id"] for m in data["modules"]}
    assert "SourceFlux[Q_hvac]" in module_ids


def test_heatsource_empty_signal_no_prescribed(client):
    """
    A HeatSource with signal="" (default) produces no prescribed signal
    and no SourceFlux module.
    """
    _add_element(client, "HeatSource", {"area": 0.0, "signal": ""})

    r = client.get(f"{BASE}/document")
    assert r.status_code == 200
    data = r.json()

    # No SourceFlux modules.
    module_types = {m["type"] for m in data["modules"]}
    assert "SourceFlux" not in module_types

    # No prescribed signals.
    roles = {s["role"] for s in data["signals"]}
    assert "prescribed" not in roles


# ── multi-orientation / adjacent-room authoring ───────────────────────────────

def test_two_orientations_produce_two_solar_modules(client):
    """
    A south window + west window → two separate SolarGain modules.
    """
    _add_element(client, "IndoorMass", INDOOR_MASS_FIELDS)
    _add_element(client, "Window", {"area": 3.0, "orientation": "S", "U": 1.2, "shgc": 0.6})
    _add_element(client, "Window", {"area": 2.0, "orientation": "W", "U": 1.5, "shgc": 0.5})

    r = client.get(f"{BASE}/document")
    assert r.status_code == 200
    data = r.json()

    module_ids = {m["id"] for m in data["modules"]}
    assert "SolarGain[G_sol_S]" in module_ids
    assert "SolarGain[G_sol_W]" in module_ids

    signal_names = {s["name"] for s in data["signals"]}
    assert "G_sol_S" in signal_names
    assert "G_sol_W" in signal_names


def test_two_adjacent_rooms_produce_two_direct_loss(client):
    """
    Two partitions to different adjacent rooms → two separate DirectLoss modules.
    """
    _add_element(client, "IndoorMass", INDOOR_MASS_FIELDS)
    _add_element(client, "Partition", {
        "area": 8.0,
        "layers": [{"material": "insulation_mineral_wool", "thickness": 0.1}],
        "adjacent": "kitchen",
    })
    _add_element(client, "Partition", {
        "area": 6.0,
        "layers": [{"material": "insulation_mineral_wool", "thickness": 0.1}],
        "adjacent": "hallway",
    })

    r = client.get(f"{BASE}/document")
    assert r.status_code == 200
    data = r.json()

    module_ids = {m["id"] for m in data["modules"]}
    assert "DirectLoss[T_kitchen]" in module_ids
    assert "DirectLoss[T_hallway]" in module_ids

    signal_names = {s["name"] for s in data["signals"]}
    assert "T_kitchen" in signal_names
    assert "T_hallway" in signal_names


def test_two_partitions_same_room_one_direct_loss(client):
    """Two partitions to the same adjacent room → one DirectLoss module."""
    _add_element(client, "IndoorMass", INDOOR_MASS_FIELDS)
    _add_element(client, "Partition", {
        "area": 8.0,
        "layers": [{"material": "insulation_mineral_wool", "thickness": 0.1}],
        "adjacent": "kitchen",
    })
    _add_element(client, "Partition", {
        "area": 4.0,
        "layers": [{"material": "insulation_mineral_wool", "thickness": 0.1}],
        "adjacent": "kitchen",
    })

    r = client.get(f"{BASE}/document")
    data = r.json()

    # Exactly one DirectLoss[T_kitchen].
    kitchen_modules = [m for m in data["modules"] if m["id"] == "DirectLoss[T_kitchen]"]
    assert len(kitchen_modules) == 1
    # Both partitions claimed.
    assert len(kitchen_modules[0]["element_ids"]) == 2


def test_heavy_wall_treatment_override(client):
    """
    A heavy wall with treatment="simple_loss" routes to DirectLoss[T_ext],
    not HeavyWall[T_ext].
    """
    _add_element(client, "IndoorMass", INDOOR_MASS_FIELDS)
    _add_element(client, "OuterWall", {
        "area": 20.0,
        "orientation": "S",
        "layers": [
            {"material": "concrete", "thickness": 0.25},
            {"material": "insulation_mineral_wool", "thickness": 0.1},
        ],
        "alpha": 0.6,
        "treatment": "simple_loss",  # override: model as simple loss
    })

    r = client.get(f"{BASE}/document")
    data = r.json()

    module_ids = {m["id"] for m in data["modules"]}
    assert "DirectLoss[T_ext]" in module_ids
    assert "HeavyWall[T_ext]" not in module_ids


def test_heavy_wall_default_routes_to_heavywall(client):
    """A heavy wall with treatment="" (default) routes to HeavyWall[T_ext]."""
    _add_element(client, "IndoorMass", INDOOR_MASS_FIELDS)
    _add_element(client, "OuterWall", {
        "area": 20.0,
        "orientation": "S",
        "layers": [
            {"material": "concrete", "thickness": 0.25},
            {"material": "insulation_mineral_wool", "thickness": 0.1},
        ],
        "alpha": 0.6,
        "treatment": "",  # default → thermal_mass for heavy wall
    })

    r = client.get(f"{BASE}/document")
    data = r.json()

    module_ids = {m["id"] for m in data["modules"]}
    assert "HeavyWall[T_ext]" in module_ids
