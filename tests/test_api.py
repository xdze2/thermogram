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


@pytest.fixture
def study():
    r = client.post("/api/studies", json={"name": "rc test"})
    assert r.status_code == 201
    s = r.json()
    yield s
    client.delete(f"/api/studies/{s['id']}")


def _patch_room(sid, room):
    return client.patch(f"/api/studies/{sid}/room", json={"room": room})


def test_rc_model_brick_room_h_env_range(study):
    r = _patch_room(study["id"], BRICK_ROOM)
    assert r.status_code == 200
    h_env = r.json()["H_env"]
    # Brick 0.20m + 0.10m mineral wool: U ≈ 0.3 W/m²K, area 12m² → ~3.6 W/K
    assert 1.0 < h_env["mu"] < 10.0
    assert h_env["sigma"] > 0
    assert len(h_env["contributions"]) == 1


def test_rc_model_deterministic(study):
    r1 = _patch_room(study["id"], BRICK_ROOM)
    r2 = _patch_room(study["id"], BRICK_ROOM)
    assert r1.json() == r2.json()


def test_rc_model_all_parameters_present(study):
    r = _patch_room(study["id"], BRICK_ROOM)
    params = {"H_env", "H_ve", "C_wall", "C_room", "alpha_eff", "H_int"}
    # Stage 5 added the module report alongside the five-parameter priors.
    report = {"modules", "signals_required", "n_free_params", "n_states", "identifiability_warning"}
    assert params | report == r.json().keys()


def test_rc_model_c_wall_has_brick_contribution(study):
    c_wall = _patch_room(study["id"], BRICK_ROOM).json()["C_wall"]
    assert c_wall["mu"] > 0
    assert any("South wall" in c["label"] for c in c_wall["contributions"])


def test_rc_model_missing_layers_returns_422(study):
    bad = {**BRICK_ROOM, "elements": [
        {
            "name": "South wall",
            "type": "wall",
            "orientation": "S",
            "area_m2": 12.0,
            "layers": [],
        }
    ]}
    r = _patch_room(study["id"], bad)
    assert r.status_code == 422


def test_rc_model_window_with_u_override(study):
    room = {**BRICK_ROOM, "elements": [
        {
            "name": "South window",
            "type": "window",
            "orientation": "S",
            "area_m2": 2.0,
            "u_value_override": 1.4,
        }
    ]}
    r = _patch_room(study["id"], room)
    assert r.status_code == 200
    data = r.json()
    # Window loss appears in H_ve contributions (direct T_ext→T_room), not H_env (opaque sol-air path)
    assert data["H_env"]["mu"] == 0.0
    win_contrib = next(c for c in data["H_ve"]["contributions"] if "window" in c["label"].lower())
    assert abs(win_contrib["value"] - 1.4 * 2.0) < 0.01


# ---------------------------------------------------------------------------
# Modules catalogue + active modules (Stage 5)
# ---------------------------------------------------------------------------

def test_modules_catalogue():
    r = client.get("/api/modules")
    assert r.status_code == 200
    names = {m["name"] for m in r.json()}
    # The current topology's modules (DirectLoss split into Ventilation + WindowLoss).
    assert {"HeavyWall", "Ventilation", "WindowLoss", "SolarGain", "RoomMass"} <= names
    heavy = next(m for m in r.json() if m["name"] == "HeavyWall")
    assert heavy["form"] == "DelayedConductance"
    assert "C_wall" in heavy["params"]
    assert "T_wall" in heavy["extra_states"]
    assert "STORAGE@—" in heavy["owns"]


def test_rc_model_reports_active_modules(study):
    data = _patch_room(study["id"], BRICK_ROOM).json()
    names = {m["name"] for m in data["modules"]}
    assert {"RoomMass", "HeavyWall", "Ventilation"} <= names
    # one heavy wall + room → 2-state aggregated topology
    assert data["n_states"] == 2
    assert data["n_free_params"] == 5
    # BRICK_ROOM has no glazing → no SolarGain → no Q_room signal.
    assert set(data["signals_required"]) == {"T_ext", "T_sa"}
    assert "SolarGain" not in names
    assert data["identifiability_warning"] is None
    heavy = next(m for m in data["modules"] if m["name"] == "HeavyWall")
    assert heavy["element"] == "South wall"


# ---------------------------------------------------------------------------
# Topology rendering (Stage 4)
# ---------------------------------------------------------------------------

def test_topology_svg(study):
    _patch_room(study["id"], BRICK_ROOM)
    r = client.get(f"/api/studies/{study['id']}/topology")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert r.content[:4] == b"<svg"


def test_topology_no_room_returns_400(study):
    r = client.get(f"/api/studies/{study['id']}/topology")
    assert r.status_code == 400


def test_topology_bad_fmt_returns_400(study):
    _patch_room(study["id"], BRICK_ROOM)
    r = client.get(f"/api/studies/{study['id']}/topology?fmt=gif")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Studies CRUD
# ---------------------------------------------------------------------------

def test_studies_create_and_list():
    r = client.post("/api/studies", json={"name": "My study"})
    assert r.status_code == 201
    study = r.json()
    assert study["name"] == "My study"
    sid = study["id"]

    r = client.get("/api/studies")
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()]
    assert sid in ids

    # cleanup
    client.delete(f"/api/studies/{sid}")


def test_studies_get():
    r = client.post("/api/studies", json={"name": "Get test"})
    sid = r.json()["id"]

    r = client.get(f"/api/studies/{sid}")
    assert r.status_code == 200
    assert r.json()["id"] == sid

    client.delete(f"/api/studies/{sid}")


def test_studies_get_missing_returns_404():
    r = client.get("/api/studies/doesnotexist")
    assert r.status_code == 404


def test_studies_rename():
    r = client.post("/api/studies", json={"name": "Old name"})
    sid = r.json()["id"]

    r = client.patch(f"/api/studies/{sid}/name", json={"name": "New name"})
    assert r.status_code == 200
    assert r.json()["name"] == "New name"

    r = client.get(f"/api/studies/{sid}")
    assert r.json()["name"] == "New name"

    client.delete(f"/api/studies/{sid}")


def test_studies_patch_room_returns_rc_prior():
    r = client.post("/api/studies", json={"name": "Room patch"})
    sid = r.json()["id"]

    payload = {"room": BRICK_ROOM}
    r = client.patch(f"/api/studies/{sid}/room", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert "H_env" in body
    assert body["H_env"]["mu"] > 0

    # rc_prior is persisted in the study
    study = client.get(f"/api/studies/{sid}").json()
    assert study["rc_prior"] is not None
    assert study["rc_prior"]["H_env"]["mu"] == body["H_env"]["mu"]

    client.delete(f"/api/studies/{sid}")


def test_studies_patch_data_spec():
    r = client.post("/api/studies", json={"name": "Data spec"})
    sid = r.json()["id"]

    spec = {"data_spec": {"signals": {"T_int": "sensor_a", "T_ext": None, "Q_sol": None}, "start": "2024-01-01", "end": "2024-01-31"}}
    r = client.patch(f"/api/studies/{sid}/data_spec", json=spec)
    assert r.status_code == 200
    assert r.json()["signals"]["T_int"] == "sensor_a"

    study = client.get(f"/api/studies/{sid}").json()
    assert study["data_spec"]["start"] == "2024-01-01"

    client.delete(f"/api/studies/{sid}")


def test_studies_duplicate():
    r = client.post("/api/studies", json={"name": "Original"})
    sid = r.json()["id"]

    r = client.post(f"/api/studies/{sid}/duplicate")
    assert r.status_code == 201
    dup = r.json()
    assert dup["id"] != sid
    assert "copy" in dup["name"].lower()

    client.delete(f"/api/studies/{sid}")
    client.delete(f"/api/studies/{dup['id']}")


def test_studies_delete():
    r = client.post("/api/studies", json={"name": "To delete"})
    sid = r.json()["id"]

    r = client.delete(f"/api/studies/{sid}")
    assert r.status_code == 204

    r = client.get(f"/api/studies/{sid}")
    assert r.status_code == 404


def test_studies_delete_missing_returns_404():
    r = client.delete("/api/studies/doesnotexist")
    assert r.status_code == 404


def test_studies_schema_version_present():
    r = client.post("/api/studies", json={"name": "Version check"})
    sid = r.json()["id"]
    assert r.json()["schema_version"] == 1

    r = client.get(f"/api/studies/{sid}")
    assert r.json()["schema_version"] == 1

    client.delete(f"/api/studies/{sid}")


def test_studies_schema_version_mismatch_returns_409(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    from thermal import study_store

    # Point the store at a temp dir with a study that has an old version
    monkeypatch.setattr(study_store, "_DATA_DIR", tmp_path)
    stale = {
        "schema_version": 0,
        "id": "aabbccdd",
        "name": "Stale study",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "room": None,
        "data_spec": {"signals": {}, "start": None, "end": None},
        "rc_prior": None,
        "fit_result": None,
    }
    (tmp_path / "aabbccdd.json").write_text(json.dumps(stale))

    r = client.get("/api/studies/aabbccdd")
    assert r.status_code == 409
    assert "schema_version" in r.json()["detail"]
