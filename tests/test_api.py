"""
Track B acceptance tests for the FastAPI backend.

Tests:
1. Author the caravan (RoomMass + DirectLoss + SolarGainModule) via CRUD,
   GET /assembly returns expected ownership/parameters/states with problems: [].
2. Deliberate double-count (two modules claim same CONDUCTION cell) surfaces
   in problems[] — not a 500.
3. POST /simulate on the caravan returns a non-constant, settling T_room.
4. GET /identifiability returns a dict with keys matching param names and
   valid status values.
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


def _add_module(client, type_: str, fields: dict | None = None) -> str:
    r = client.post(f"{BASE}/modules", json={"type": type_, "fields": fields or {}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _set_routing(client, mid: str, element_ids: list[str]) -> None:
    r = client.put(f"{BASE}/modules/{mid}/routing", json={"element_ids": element_ids})
    assert r.status_code == 200, r.text


def _build_caravan(client) -> tuple[str, str, str, str, str, str]:
    """
    Build the caravan: IndoorMass + OuterWall (light) + Window,
    RoomMass (no fields), DirectLoss, SolarGainModule.
    Returns (im_eid, wall_eid, win_eid, rm_mid, dl_mid, sg_mid).
    """
    im_eid = _add_element(client, "IndoorMass", INDOOR_MASS_FIELDS)
    wall_eid = _add_element(client, "OuterWall", LIGHT_WALL_FIELDS)
    win_eid = _add_element(client, "Window", WINDOW_FIELDS)

    rm_mid = _add_module(client, "RoomMass")  # no fields — pure topology
    dl_mid = _add_module(client, "DirectLoss")
    sg_mid = _add_module(client, "SolarGainModule")

    _set_routing(client, dl_mid, [wall_eid, win_eid])
    _set_routing(client, sg_mid, [win_eid])

    return im_eid, wall_eid, win_eid, rm_mid, dl_mid, sg_mid


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
    assert data["modules"] == []


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


def test_add_and_delete_module(client):
    mid = _add_module(client, "RoomMass")  # no fields — pure topology
    r = client.get(f"{BASE}/document")
    assert any(m["id"] == mid for m in r.json()["modules"])

    r = client.delete(f"{BASE}/modules/{mid}")
    assert r.status_code == 204

    r = client.get(f"{BASE}/document")
    assert all(m["id"] != mid for m in r.json()["modules"])


def test_delete_element_removes_from_routing(client):
    eid = _add_element(client, "Window", WINDOW_FIELDS)
    mid = _add_module(client, "DirectLoss")
    _set_routing(client, mid, [eid])

    client.delete(f"{BASE}/elements/{eid}")

    r = client.get(f"{BASE}/document")
    mod = next(m for m in r.json()["modules"] if m["id"] == mid)
    assert eid not in mod["element_ids"]


def test_routing_unknown_element_404(client):
    mid = _add_module(client, "DirectLoss")
    r = client.put(f"{BASE}/modules/{mid}/routing", json={"element_ids": ["e999"]})
    assert r.status_code == 404


def test_unknown_model_404(client):
    r = client.get("/api/models/nonexistent/document")
    assert r.status_code == 404


# ── assembly: caravan valid ────────────────────────────────────────────────────

def test_assembly_caravan_no_problems(client):
    """
    Test 1: caravan assembled correctly — ownership/parameters/states present,
    problems is empty.
    """
    im_eid, wall_eid, win_eid, rm_mid, dl_mid, sg_mid = _build_caravan(client)

    r = client.get(f"{BASE}/assembly")
    assert r.status_code == 200
    data = r.json()

    assert data["problems"] == [], data["problems"]
    assert "T_room" in data["states"]
    assert "T_ext" in data["signals"]
    assert "G_sol" in data["signals"]

    param_names = {p["name"] for p in data["parameters"]}
    assert "H_ve" in param_names
    assert "shgcA" in param_names
    assert "C_room" in param_names

    # Ownership: CONDUCTION on wall -> DirectLoss, SOLAR_TRANSMISSION on window -> SolarGain
    channels_owned = {(o["element_id"], o["channel"]) for o in data["ownership"]}
    assert (wall_eid, "CONDUCTION") in channels_owned
    assert (win_eid, "SOLAR_TRANSMISSION") in channels_owned


def test_assembly_graph_nodes_and_edges(client):
    _build_caravan(client)
    r = client.get(f"{BASE}/assembly")
    data = r.json()

    node_ids = {n["id"] for n in data["graph"]["nodes"]}
    assert "T_room" in node_ids
    assert "T_ext" in node_ids
    assert "G_sol" in node_ids

    # At least one edge points to T_room
    assert any(e["to"] == "T_room" for e in data["graph"]["edges"])


def test_assembly_parameter_contributions(client):
    im_eid, wall_eid, win_eid, rm_mid, dl_mid, sg_mid = _build_caravan(client)
    r = client.get(f"{BASE}/assembly")
    data = r.json()

    h_ve = next(p for p in data["parameters"] if p["name"] == "H_ve")
    assert len(h_ve["contributions"]) > 0
    contrib_eids = {c["element_id"] for c in h_ve["contributions"]}
    # Wall and window both contribute CONDUCTION -> H_ve
    assert wall_eid in contrib_eids or win_eid in contrib_eids


# ── assembly: missing room mass ────────────────────────────────────────────────

def test_assembly_missing_room_mass(client):
    """Assembly with no RoomMass returns problems but no 500."""
    _add_element(client, "Window", WINDOW_FIELDS)
    r = client.get(f"{BASE}/assembly")
    assert r.status_code == 200
    data = r.json()
    kinds = [p["kind"] for p in data["problems"]]
    assert "missing_room_mass" in kinds


# ── assembly: double-count surfaces as problem ─────────────────────────────────

def test_assembly_double_count_in_problems(client):
    """
    Test 2: two modules claiming the same (element, CONDUCTION) cell surfaces
    in problems[] without a 500.
    """
    _add_element(client, "IndoorMass", INDOOR_MASS_FIELDS)
    win_eid = _add_element(client, "Window", WINDOW_FIELDS)
    _add_module(client, "RoomMass")  # no fields

    dl1 = _add_module(client, "DirectLoss")
    dl2 = _add_module(client, "DirectLoss")
    _set_routing(client, dl1, [win_eid])
    _set_routing(client, dl2, [win_eid])  # same window claimed by two DirectLoss

    r = client.get(f"{BASE}/assembly")
    assert r.status_code == 200
    kinds = [p["kind"] for p in r.json()["problems"]]
    assert "double_count" in kinds


# ── simulate ───────────────────────────────────────────────────────────────────

def test_simulate_caravan_settling(client):
    """
    Test 3: simulate the caravan — T_room is non-constant and settles toward
    a warmer equilibrium when T_ext > initial T_room.
    """
    _build_caravan(client)

    n = 48  # 48 hours
    T_ext = [20.0] * n   # constant warm exterior
    G_sol = [0.0] * n

    body = {
        "signals": {"T_ext": T_ext, "G_sol": G_sol},
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
        "signals": {"T_ext": [20.0] * 5, "G_sol": [0.0] * 5},
        "dt": 3600.0,
    }
    r = client.post(f"{BASE}/simulate", json=body)
    assert r.status_code == 400


# ── identifiability ────────────────────────────────────────────────────────────

def test_identifiability_caravan(client):
    """
    Test 4: GET /identifiability returns a param_status dict with all param names
    and valid status values.
    """
    _build_caravan(client)

    r = client.get(f"{BASE}/identifiability")
    assert r.status_code == 200, r.text
    data = r.json()

    assert "param_status" in data
    ps = data["param_status"]
    assert set(ps.keys()) >= {"H_ve", "shgcA", "C_room"}

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
