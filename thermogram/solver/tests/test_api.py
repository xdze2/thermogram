"""API-level tests for thermogram.api.main.

Uses FastAPI's TestClient (httpx transport) — no live server needed.
Tests:
- 422 on malformed house / study bodies
- PUT /houses then GET round-trip preserves all fields
- POST /houses/{name}/expand returns a payload that validates as AtomicModel
- Study CRUD: create → get → put → delete
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thermogram.models import AtomicModel, House

_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with houses stored in a temp directory."""
    import thermogram.api.main as main_module

    monkeypatch.setattr(main_module, "HOUSES_DIR", tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)

    from fastapi.testclient import TestClient as TC
    return TC(main_module.app)


@pytest.fixture()
def valid_house_payload():
    return json.loads((_FIXTURES / "maison_test.json").read_text())


# ── 422 validation ────────────────────────────────────────────────────────────

def test_put_house_rejects_malformed(client):
    """A body that fails Pydantic validation should return 422."""
    r = client.put("/houses/test_bad", json={"rooms": "not-a-list"})
    assert r.status_code == 422


def test_put_house_rejects_bad_element_kind(client):
    """An element with an unknown 'kind' should be rejected."""
    payload = {
        "schema_version": "0.3",
        "rooms": [],
        "elements": [{"id": str(uuid.uuid4()), "label": "X", "kind": "unknown_kind"}],
        "studies": [],
    }
    r = client.put("/houses/bad_kind", json=payload)
    assert r.status_code == 422


def test_create_study_rejects_bad_uuid(client, valid_house_payload):
    """PUT study with a non-UUID id should fail."""
    client.put("/houses/h1", json=valid_house_payload)
    r = client.put(
        "/houses/h1/studies/not-a-uuid",
        json={"id": "not-a-uuid", "type": "run", "start": "", "end": ""},
    )
    assert r.status_code == 422


# ── round-trip PUT → GET ──────────────────────────────────────────────────────

def test_put_get_house_roundtrip(client, valid_house_payload):
    """PUT then GET must preserve every field (modulo computed _ prefixes)."""
    r = client.put("/houses/myhouse", json=valid_house_payload)
    assert r.status_code == 200, r.text

    r2 = client.get("/houses/myhouse")
    assert r2.status_code == 200

    got = r2.json()
    # Validate that the response parses as House
    House.model_validate(got)

    # All original rooms preserved
    orig_room_ids = {rm["id"] for rm in valid_house_payload.get("rooms", [])}
    got_room_ids  = {rm["id"] for rm in got.get("rooms", [])}
    assert orig_room_ids == got_room_ids

    # All original elements preserved
    orig_el_ids = {el["id"] for el in valid_house_payload.get("elements", [])}
    got_el_ids  = {el["id"] for el in got.get("elements", [])}
    assert orig_el_ids == got_el_ids


def test_get_house_returns_model_hash(client, valid_house_payload):
    client.put("/houses/h_hash", json=valid_house_payload)
    r = client.get("/houses/h_hash")
    assert r.status_code == 200
    data = r.json()
    assert "_model_hash" in data
    assert isinstance(data["_model_hash"], str) and len(data["_model_hash"]) > 0


def test_get_nonexistent_house_returns_404(client):
    r = client.get("/houses/does_not_exist")
    assert r.status_code == 404


# ── expand validates as AtomicModel ──────────────────────────────────────────

def test_expand_returns_valid_atomic_model(client, valid_house_payload):
    client.put("/houses/exp_house", json=valid_house_payload)
    r = client.post("/houses/exp_house/expand")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "model" in data
    # Must validate as AtomicModel without error
    AtomicModel.model_validate(data["model"])


# ── study CRUD ────────────────────────────────────────────────────────────────

def test_study_create_get_put_delete(client, valid_house_payload):
    client.put("/houses/hs", json=valid_house_payload)

    # create
    r = client.post("/houses/hs/studies", json={"label": "test study", "type": "run"})
    assert r.status_code == 200
    sid = r.json()["id"]

    # get
    r2 = client.get(f"/houses/hs/studies/{sid}")
    assert r2.status_code == 200
    study = r2.json()
    assert study["id"] == sid
    assert "_stale_run" in study

    # put — update the label
    updated = {**study, "label": "renamed"}
    r3 = client.put(f"/houses/hs/studies/{sid}", json=updated)
    assert r3.status_code == 200

    r4 = client.get(f"/houses/hs/studies/{sid}")
    assert r4.json()["label"] == "renamed"

    # delete
    r5 = client.delete(f"/houses/hs/studies/{sid}")
    assert r5.status_code == 200

    r6 = client.get(f"/houses/hs/studies/{sid}")
    assert r6.status_code == 404


def test_get_nonexistent_study_returns_404(client, valid_house_payload):
    client.put("/houses/hs2", json=valid_house_payload)
    r = client.get(f"/houses/hs2/studies/{uuid.uuid4()}")
    assert r.status_code == 404


# ── list houses ───────────────────────────────────────────────────────────────

def test_list_houses_empty(client):
    r = client.get("/houses")
    assert r.status_code == 200
    assert r.json() == []


def test_list_houses_after_create(client, valid_house_payload):
    client.put("/houses/h_list", json=valid_house_payload)
    r = client.get("/houses")
    assert r.status_code == 200
    names = [h["name"] for h in r.json()]
    assert "h_list" in names


# ── view routes ───────────────────────────────────────────────────────────────

@pytest.fixture()
def house_with_study(client, valid_house_payload):
    """House 'vh' with one study; returns (house_name, study_id)."""
    client.put("/houses/vh", json=valid_house_payload)
    r = client.post("/houses/vh/studies", json={"label": "s1", "type": "fit"})
    assert r.status_code == 200
    return "vh", r.json()["id"]


def test_post_view_builds_and_returns(client, house_with_study):
    name, sid = house_with_study
    r = client.post(f"/houses/{name}/studies/{sid}/view")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "lumped" in data
    assert len(data["lumped"]) > 0
    assert data["_stale_view"] is False
    assert "model_hash" in data


def test_get_view_returns_fresh(client, house_with_study):
    name, sid = house_with_study
    client.post(f"/houses/{name}/studies/{sid}/view")
    r = client.get(f"/houses/{name}/studies/{sid}/view")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "lumped" in data
    assert data["_stale_view"] is False


def test_get_view_404_before_build(client, house_with_study):
    name, sid = house_with_study
    r = client.get(f"/houses/{name}/studies/{sid}/view")
    assert r.status_code == 404


def test_put_view_updates_mode(client, house_with_study):
    name, sid = house_with_study
    r = client.post(f"/houses/{name}/studies/{sid}/view")
    lumped = r.json()["lumped"]
    # Find a free lump and flip it to fixed
    free_lumps = [l for l in lumped if l.get("mode") == "free"]
    assert free_lumps, "Expected at least one free lump in maison_test"
    target_id = free_lumps[0]["id"]

    r2 = client.put(
        f"/houses/{name}/studies/{sid}/view",
        json={"lumped": [{"id": target_id, "mode": "fixed"}]},
    )
    assert r2.status_code == 200, r2.text

    r3 = client.get(f"/houses/{name}/studies/{sid}/view")
    updated = {l["id"]: l for l in r3.json()["lumped"]}
    assert updated[target_id]["mode"] == "fixed"


def test_view_stale_after_house_edit(client, house_with_study):
    name, sid = house_with_study
    client.post(f"/houses/{name}/studies/{sid}/view")

    # Read back the current house (includes studies with the view)
    house_data = client.get(f"/houses/{name}").json()
    # Change a room label — enough to shift model_hash
    if house_data.get("rooms"):
        house_data["rooms"][0]["label"] = "edited_label_xyz"
    client.put(f"/houses/{name}", json=house_data)

    r = client.get(f"/houses/{name}/studies/{sid}/view")
    assert r.status_code == 200
    assert r.json()["_stale_view"] is True


def test_fit_run_rejects_missing_view(client, house_with_study):
    name, sid = house_with_study
    payload = {
        "house_name": name,
        "study_id": sid,
        "start": "2024-01-01T00:00:00",
        "end": "2024-01-02T00:00:00",
        "inputs": {},
        "observations": {},
    }
    r = client.post("/fit/run", json=payload)
    assert r.status_code == 400
    assert "view" in r.json()["detail"].lower()


def test_fit_run_rejects_stale_view(client, house_with_study):
    name, sid = house_with_study
    client.post(f"/houses/{name}/studies/{sid}/view")

    house_data = client.get(f"/houses/{name}").json()
    if house_data.get("rooms"):
        house_data["rooms"][0]["label"] = "edited_xyz"
    client.put(f"/houses/{name}", json=house_data)

    payload = {
        "house_name": name,
        "study_id": sid,
        "start": "2024-01-01T00:00:00",
        "end": "2024-01-02T00:00:00",
        "inputs": {},
        "observations": {},
    }
    r = client.post("/fit/run", json=payload)
    assert r.status_code == 409
    assert "stale" in r.json()["detail"].lower()


def test_preview_groups_removed(client):
    """The old /fit/preview-groups endpoint must not exist."""
    r = client.post("/fit/preview-groups", json={"atomic_model": {}, "param_keys": []})
    assert r.status_code == 404 or r.status_code == 405
