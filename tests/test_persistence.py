"""
Persistence and multi-model address-space tests.

Coverage:
- POST /api/models creates a model, returns {uid, name}
- After element add, user_data/{uid}.json appears and contains the element
- Simulate a restart: clear _store, re-run load_all_models, model + element
  survive
- Round-trip: author → save → clear store → load → identical document
- Rename changes name only, not uid; file is updated
- DELETE removes model from store and deletes user_data/{uid}.json
- GET /api/models lists models; filtered to those with a uid
- POST /api/models/from_example returns 503 while examples.py is absent
- GET /api/models/examples returns [] while examples.py is absent
- Counter round-trip: new IDs after reload don't collide with pre-existing ones

All file I/O is redirected to a temporary directory (monkeypatching
store.USER_DATA_DIR) so tests never touch the real user_data/.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from thnodes.api.app import app
from thnodes.api import store as store_module
from thnodes.api.store import (
    _store,
    load_all_models,
    roomdoc_from_dict,
    roomdoc_to_dict,
    save_model,
)
from thnodes.api.models import RoomDoc, ElementSpec, ModuleSpec


# ── fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_data(tmp_path: pathlib.Path, monkeypatch):
    """
    Redirect USER_DATA_DIR to a fresh temp directory and clear _store.
    The monkeypatch is applied before the TestClient lifespan fires, so the
    lifespan's load_all_models() call uses the temp dir (which is empty).
    """
    data_dir = tmp_path / "user_data"
    data_dir.mkdir()
    monkeypatch.setattr(store_module, "USER_DATA_DIR", data_dir)
    _store.clear()
    yield data_dir
    _store.clear()


@pytest.fixture()
def client(tmp_data):
    """TestClient whose lifespan fires against the patched empty tmp_data dir."""
    with TestClient(app) as c:
        yield c


# ── helpers ────────────────────────────────────────────────────────────────────

WINDOW_FIELDS = {
    "area": 4.0,
    "orientation": "S",
    "U": 1.2,
    "shgc": 0.6,
}


def _create_model(client, name: str = "TestModel") -> str:
    r = client.post("/api/models", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["uid"]


def _add_element(client, uid: str, type_: str, fields: dict) -> str:
    r = client.post(f"/api/models/{uid}/elements", json={"type": type_, "fields": fields})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── GET /api/models ────────────────────────────────────────────────────────────

def test_list_models_empty_then_one(client, tmp_data):
    """After startup with empty user_data/, list shows the default model only."""
    r = client.get("/api/models")
    assert r.status_code == 200
    # The lifespan seeds "default" when the store would otherwise be empty.
    # (tmp_data is empty, so lifespan creates one model with uid "default".)
    models = r.json()
    assert len(models) == 1
    assert models[0]["uid"] == "default"


def test_list_models_after_create(client, tmp_data):
    uid = _create_model(client, "Alpha")
    r = client.get("/api/models")
    uids = [m["uid"] for m in r.json()]
    assert uid in uids


# ── POST /api/models ───────────────────────────────────────────────────────────

def test_create_model_returns_uid_and_name(client, tmp_data):
    r = client.post("/api/models", json={"name": "My Model"})
    assert r.status_code == 201
    data = r.json()
    assert "uid" in data
    assert data["name"] == "My Model"
    assert len(data["uid"]) == 32  # uuid4().hex


def test_create_model_default_name(client, tmp_data):
    r = client.post("/api/models", json={})
    assert r.status_code == 201
    assert r.json()["name"] == "Untitled"


def test_create_model_writes_json_file(client, tmp_data):
    uid = _create_model(client, "Persisted")
    json_file = tmp_data / f"{uid}.json"
    assert json_file.exists(), f"Expected {json_file} to exist"
    d = json.loads(json_file.read_text())
    assert d["uid"] == uid
    assert d["name"] == "Persisted"


# ── auto-save after element add ────────────────────────────────────────────────

def test_autosave_after_add_element(client, tmp_data):
    """After adding an element, the JSON file must contain that element."""
    uid = _create_model(client, "AutoSave")
    eid = _add_element(client, uid, "Window", WINDOW_FIELDS)

    json_file = tmp_data / f"{uid}.json"
    d = json.loads(json_file.read_text())
    assert eid in d["elements"], f"Element {eid!r} not found in persisted file"
    assert d["elements"][eid]["type"] == "Window"


# ── restart simulation: clear store + reload ──────────────────────────────────

def test_restart_roundtrip(client, tmp_data):
    """
    Create a model + element, then simulate a server restart by clearing
    _store and calling load_all_models.  The model must come back intact.
    """
    uid = _create_model(client, "Restart")
    eid = _add_element(client, uid, "Window", WINDOW_FIELDS)

    # Simulate restart: clear in-memory store, re-load from disk.
    _store.clear()
    load_all_models()

    assert uid in _store, "Model did not survive reload"
    doc = _store[uid]
    assert doc.name == "Restart"
    assert eid in doc.elements
    assert doc.elements[eid].type == "Window"
    assert doc.elements[eid].fields["area"] == pytest.approx(4.0)


def test_restart_counter_no_collision(client, tmp_data):
    """
    After reload, new element IDs must not collide with pre-existing ones.
    """
    uid = _create_model(client, "Counters")
    # Add two elements so counter is at 2.
    _add_element(client, uid, "Window", WINDOW_FIELDS)
    _add_element(client, uid, "Window", WINDOW_FIELDS)

    _store.clear()
    load_all_models()

    doc = _store[uid]
    existing_ids = set(doc.elements.keys())
    new_eid = doc.next_element_id()
    assert new_eid not in existing_ids, f"New ID {new_eid!r} collides with existing {existing_ids}"


# ── full round-trip via serialisation functions ────────────────────────────────

def test_roomdoc_roundtrip_serialisation():
    """roomdoc_to_dict → roomdoc_from_dict must produce an identical document."""
    original = RoomDoc(uid="abc123", name="Round-trip")
    original.elements["e0"] = ElementSpec(type="Window", fields={"area": 5.0, "orientation": "S", "U": 1.1, "shgc": 0.5})
    original.elements["e1"] = ElementSpec(type="OuterWall", fields={"area": 10.0})
    original.modules["m0"] = ModuleSpec(type="RoomMass", fields={})
    original.routes["m0"] = ["e0", "e1"]
    original._elem_counter = 2
    original._mod_counter = 1

    d = roomdoc_to_dict(original)
    restored = roomdoc_from_dict(d)

    assert restored.uid == "abc123"
    assert restored.name == "Round-trip"
    assert set(restored.elements.keys()) == {"e0", "e1"}
    assert restored.elements["e0"].type == "Window"
    assert restored.elements["e0"].fields["area"] == pytest.approx(5.0)
    assert restored.modules["m0"].type == "RoomMass"
    assert restored.routes["m0"] == ["e0", "e1"]
    assert restored._elem_counter == 2
    assert restored._mod_counter == 1


def test_roomdoc_from_dict_missing_counters():
    """
    When counters are absent (example dict shape), counters default to
    max-existing-id + 1.
    """
    d = {
        "uid": "ex1",
        "name": "Example",
        "elements": {"e0": {"type": "Window", "fields": {}}, "e3": {"type": "Window", "fields": {}}},
        "modules": {"m1": {"type": "RoomMass", "fields": {}}},
        "routes": {},
        # No _elem_counter / _mod_counter
    }
    doc = roomdoc_from_dict(d)
    # max element suffix is 3, so counter = 4
    assert doc._elem_counter == 4
    # max module suffix is 1, so counter = 2
    assert doc._mod_counter == 2


# ── PATCH /api/models/{uid} (rename) ──────────────────────────────────────────

def test_rename_changes_name_not_uid(client, tmp_data):
    uid = _create_model(client, "Old Name")
    r = client.patch(f"/api/models/{uid}", json={"name": "New Name"})
    assert r.status_code == 200
    data = r.json()
    assert data["uid"] == uid          # UID unchanged
    assert data["name"] == "New Name"

    # Check the in-memory store
    assert _store[uid].name == "New Name"


def test_rename_persists_to_file(client, tmp_data):
    uid = _create_model(client, "Before")
    client.patch(f"/api/models/{uid}", json={"name": "After"})
    d = json.loads((tmp_data / f"{uid}.json").read_text())
    assert d["name"] == "After"
    assert d["uid"] == uid


def test_rename_unknown_model_404(client, tmp_data):
    r = client.patch("/api/models/nonexistent_uid_xyz", json={"name": "whatever"})
    assert r.status_code == 404


# ── DELETE /api/models/{uid} ──────────────────────────────────────────────────

def test_delete_model(client, tmp_data):
    uid = _create_model(client, "ToDelete")
    json_file = tmp_data / f"{uid}.json"
    assert json_file.exists()

    r = client.delete(f"/api/models/{uid}")
    assert r.status_code == 204

    # Removed from store
    assert uid not in _store

    # File deleted
    assert not json_file.exists()


def test_delete_model_not_in_list(client, tmp_data):
    uid = _create_model(client, "Gone")
    client.delete(f"/api/models/{uid}")
    uids = [m["uid"] for m in client.get("/api/models").json()]
    assert uid not in uids


def test_delete_unknown_model_404(client, tmp_data):
    r = client.delete("/api/models/does_not_exist_xyz")
    assert r.status_code == 404


# ── GET /api/models/examples ──────────────────────────────────────────────────

def test_list_examples_returns_list(client, tmp_data):
    """
    While examples.py is absent, returns an empty list (not an error).
    Once examples.py exists, returns at least one entry with key + name.
    """
    r = client.get("/api/models/examples")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    # Each entry must have key and name if any items are present.
    for item in data:
        assert "key" in item
        assert "name" in item


# ── POST /api/models/from_example ────────────────────────────────────────────

def test_from_example_unknown_key_error(client, tmp_data):
    """
    POST /models/from_example with an unknown key must not return 500.
    When examples.py is absent:  503.
    When examples.py is present: the endpoint raises KeyError from load_example,
    which propagates as a 500 unless we catch it — so this test verifies the
    endpoint handles it gracefully (not 500).

    We use a key that is guaranteed not to exist in any realistic examples set.
    """
    r = client.post(
        "/api/models/from_example",
        json={"example_key": "_no_such_example_key_xyz_"},
    )
    # Acceptable outcomes: 503 (module absent), 404/422 (key invalid), or
    # 201 (highly unlikely with a nonsense key).  Must never be 500.
    assert r.status_code != 500, f"Got unexpected 500: {r.text}"


def test_from_example_creates_model(client, tmp_data):
    """
    POST /models/from_example with a known key must create a new model.
    Skipped when examples.py is absent (503).
    """
    r = client.post("/api/models/from_example", json={"example_key": "caravan"})
    if r.status_code == 503:
        pytest.skip("examples.py not yet deployed")
    assert r.status_code == 201, r.text
    data = r.json()
    assert "uid" in data
    # Default name comes from the example dict when caller doesn't supply one.
    assert data["name"]

    # Verify the new model appears in the list.
    uids = [m["uid"] for m in client.get("/api/models").json()]
    assert data["uid"] in uids

    # JSON file must exist.
    json_file = tmp_data / f"{data['uid']}.json"
    assert json_file.exists()


def test_from_example_custom_name(client, tmp_data):
    """Caller-supplied name overrides the example's own name."""
    r = client.post(
        "/api/models/from_example",
        json={"example_key": "caravan", "name": "My Caravan"},
    )
    if r.status_code == 503:
        pytest.skip("examples.py not yet deployed")
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "My Caravan"


def test_from_example_each_load_is_independent(client, tmp_data):
    """Two loads of the same example produce two independent models."""
    r1 = client.post("/api/models/from_example", json={"example_key": "caravan"})
    r2 = client.post("/api/models/from_example", json={"example_key": "caravan"})
    if r1.status_code == 503 or r2.status_code == 503:
        pytest.skip("examples.py not yet deployed")
    assert r1.status_code == r2.status_code == 201
    uid1 = r1.json()["uid"]
    uid2 = r2.json()["uid"]
    assert uid1 != uid2, "Each load must produce a distinct UID"

    # Mutate one; the other must be unaffected.
    doc1_elements_before = set(_store[uid1].elements.keys())
    # Delete an element from uid2
    some_eid = next(iter(_store[uid2].elements))
    client.delete(f"/api/models/{uid2}/elements/{some_eid}")
    # uid1 must be unchanged
    assert set(_store[uid1].elements.keys()) == doc1_elements_before


# ── document mutation routes still save when uid is set ───────────────────────

def test_document_mutation_autosave_patch_element(client, tmp_data):
    """PATCH /elements also triggers auto-save."""
    uid = _create_model(client, "PatchTest")
    eid = _add_element(client, uid, "Window", WINDOW_FIELDS)
    client.patch(f"/api/models/{uid}/elements/{eid}", json={"fields": {"area": 99.0}})
    d = json.loads((tmp_data / f"{uid}.json").read_text())
    assert d["elements"][eid]["fields"]["area"] == pytest.approx(99.0)


def test_document_mutation_autosave_delete_element(client, tmp_data):
    """DELETE /elements also triggers auto-save; element must be absent from file."""
    uid = _create_model(client, "DeleteElemTest")
    eid = _add_element(client, uid, "Window", WINDOW_FIELDS)
    client.delete(f"/api/models/{uid}/elements/{eid}")
    d = json.loads((tmp_data / f"{uid}.json").read_text())
    assert eid not in d["elements"]


def test_document_mutation_autosave_routing(client, tmp_data):
    """PUT /routing also triggers auto-save."""
    uid = _create_model(client, "RoutingTest")
    eid = _add_element(client, uid, "Window", WINDOW_FIELDS)
    r = client.post(f"/api/models/{uid}/modules", json={"type": "DirectLoss", "fields": {}})
    mid = r.json()["id"]
    client.put(f"/api/models/{uid}/modules/{mid}/routing", json={"element_ids": [eid]})
    d = json.loads((tmp_data / f"{uid}.json").read_text())
    assert mid in d["routes"]
    assert eid in d["routes"][mid]
