import pytest
from fastapi.testclient import TestClient

from api import app

client = TestClient(app)

BRICK_ROOM = {
    "name": "Test room",
    "floor_area_m2": 20.0,
    "height_m": 2.5,
    "latitude": 48.85,
    "longitude": 2.35,
    "ach": 0.5,
    "elements": [
        {
            "name": "South wall",
            "type": "wall",
            "orientation": "S",
            "area_m2": 12.0,
            "layers": [
                {"material_key": "brick_common", "thickness_m": 0.20},
                {"material_key": "mineral_wool", "thickness_m": 0.10},
                {"material_key": "gypsum_board", "thickness_m": 0.013},
            ],
        }
    ],
}


def test_schema_returns_element_types_and_orientations():
    r = client.get("/api/schema")
    assert r.status_code == 200
    body = r.json()
    assert "element_types" in body
    assert "orientations" in body
    et_values = [e["value"] for e in body["element_types"]]
    assert "wall" in et_values
    assert "window" in et_values
    or_values = [o["value"] for o in body["orientations"]]
    assert "S" in or_values
    assert "horizontal" in or_values


def test_materials_non_empty():
    r = client.get("/api/materials")
    assert r.status_code == 200
    materials = r.json()
    assert len(materials) > 0
    keys = [m["key"] for m in materials]
    assert "brick_common" in keys
    assert "mineral_wool" in keys


def test_materials_schema():
    r = client.get("/api/materials")
    first = r.json()[0]
    assert {"key", "name", "lambda_W_mK", "rho_kg_m3", "cp_J_kgK", "is_heavy"} <= first.keys()


def test_rc_model_brick_room_h_env_range():
    r = client.post("/api/room/rc_model", json=BRICK_ROOM)
    assert r.status_code == 200
    body = r.json()
    h_env = body["H_env"]
    # Brick 0.20m + 0.10m mineral wool: U ≈ 0.3 W/m²K, area 12m² → ~3.6 W/K
    assert 1.0 < h_env["mu"] < 10.0
    assert h_env["sigma"] > 0
    assert len(h_env["contributions"]) == 1


def test_rc_model_deterministic():
    r1 = client.post("/api/room/rc_model", json=BRICK_ROOM)
    r2 = client.post("/api/room/rc_model", json=BRICK_ROOM)
    assert r1.json() == r2.json()


def test_rc_model_all_parameters_present():
    r = client.post("/api/room/rc_model", json=BRICK_ROOM)
    body = r.json()
    assert {"H_env", "H_ve", "C_wall", "C_room", "alpha_eff"} == body.keys()


def test_rc_model_c_wall_has_brick_contribution():
    r = client.post("/api/room/rc_model", json=BRICK_ROOM)
    c_wall = r.json()["C_wall"]
    assert c_wall["mu"] > 0
    assert any("South wall" in c["label"] for c in c_wall["contributions"])


def test_rc_model_missing_layers_returns_422():
    bad = {**BRICK_ROOM, "elements": [
        {
            "name": "South wall",
            "type": "wall",
            "orientation": "S",
            "area_m2": 12.0,
            "layers": [],
        }
    ]}
    r = client.post("/api/room/rc_model", json=bad)
    assert r.status_code == 422


def test_rc_model_window_with_u_override():
    room = {**BRICK_ROOM, "elements": [
        {
            "name": "South window",
            "type": "window",
            "orientation": "S",
            "area_m2": 2.0,
            "u_value_override": 1.4,
        }
    ]}
    r = client.post("/api/room/rc_model", json=room)
    assert r.status_code == 200
    h_env = r.json()["H_env"]
    assert abs(h_env["mu"] - 1.4 * 2.0) < 0.01
