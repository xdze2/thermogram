"""
Phase D1 acceptance tests — document & registry data shapes.

Coverage (per workstream spec):
1. RoomDoc with signals + new element fields round-trips through
   roomdoc_to_dict / roomdoc_from_dict losslessly.
2. A Signal of each role/kind serialises and restores correctly.
3. next_signal_id() yields s0, s1, …; _signal_counter recovers from a dict
   that lacks it (max-suffix-fallback pattern).
4. Partition(adjacent=…), Floor(…, adjacent_room=…), OuterWall(…, treatment=…)
   all construct without error and carry the new fields.
5. GET /registry exposes boundary + treatments per element type; OuterWall has
   the 2-entry treatment menu; all other types have treatments=[].
6. Regression: existing examples still load; GET /document still returns
   elements + modules (routing intact) AND now also returns signals.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from thnodes.api.app import app
from thnodes.api.models import RoomDoc, Signal, ElementSpec, ModuleSpec
from thnodes.api.store import (
    _store,
    roomdoc_from_dict,
    roomdoc_to_dict,
    signal_to_out,
)
from thnodes.elements import Floor, OuterWall, Partition, Layer


# ── fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_store():
    """Isolate each test: clear _store, seed a bare default doc."""
    _store.clear()
    _store["default"] = RoomDoc()
    yield
    _store.clear()
    _store["default"] = RoomDoc()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


BASE = "/api/models/default"

_INSULATION_LAYER = {"material": "insulation_mineral_wool", "thickness": 0.1}
_CONCRETE_LAYER = {"material": "concrete_normal", "thickness": 0.2}


# ── 1. RoomDoc round-trip with signals + new element fields ───────────────────


def test_roomdoc_roundtrip_with_signals():
    """
    RoomDoc containing Signal objects round-trips through
    roomdoc_to_dict / roomdoc_from_dict without data loss.
    """
    doc = RoomDoc(uid="rt1", name="RoundTrip")
    # Add signals of different roles/kinds.
    doc.signals["s0"] = Signal(
        id="s0", name="T_ext", kind="temperature", role="exterior"
    )
    doc.signals["s1"] = Signal(
        id="s1",
        name="G_sol_S",
        kind="irradiance",
        role="solar",
        meta={"orientation": "S"},
    )
    doc.signals["s2"] = Signal(
        id="s2", name="T_kitchen", kind="temperature", role="adjacent"
    )
    doc._signal_counter = 3

    # Add elements with new boundary fields.
    doc.elements["e0"] = ElementSpec(
        type="Partition",
        fields={"area": 8.0, "layers": [_INSULATION_LAYER], "adjacent": "kitchen"},
    )
    doc.elements["e1"] = ElementSpec(
        type="Floor",
        fields={
            "area": 20.0,
            "boundary": "adjacent",
            "layers": [_CONCRETE_LAYER],
            "adjacent_room": "basement",
        },
    )
    doc.elements["e2"] = ElementSpec(
        type="OuterWall",
        fields={
            "area": 12.0,
            "orientation": "S",
            "layers": [_CONCRETE_LAYER],
            "alpha": 0.6,
            "treatment": "simple_loss",
        },
    )
    doc._elem_counter = 3

    serialised = roomdoc_to_dict(doc)
    restored = roomdoc_from_dict(serialised)

    # Top-level identity.
    assert restored.uid == "rt1"
    assert restored.name == "RoundTrip"

    # Signals.
    assert set(restored.signals.keys()) == {"s0", "s1", "s2"}
    assert restored.signals["s0"].name == "T_ext"
    assert restored.signals["s0"].kind == "temperature"
    assert restored.signals["s0"].role == "exterior"
    assert restored.signals["s0"].meta == {}

    assert restored.signals["s1"].name == "G_sol_S"
    assert restored.signals["s1"].kind == "irradiance"
    assert restored.signals["s1"].role == "solar"
    assert restored.signals["s1"].meta == {"orientation": "S"}

    assert restored.signals["s2"].name == "T_kitchen"
    assert restored.signals["s2"].role == "adjacent"

    # Signal counter.
    assert restored._signal_counter == 3

    # Element boundary fields.
    assert restored.elements["e0"].fields["adjacent"] == "kitchen"
    assert restored.elements["e1"].fields["adjacent_room"] == "basement"
    assert restored.elements["e2"].fields["treatment"] == "simple_loss"

    # Element counter.
    assert restored._elem_counter == 3


# ── 2. Each role/kind round-trips ────────────────────────────────────────────


@pytest.mark.parametrize(
    "role, kind, meta",
    [
        ("exterior", "temperature", {}),
        ("ground", "temperature", {}),
        ("adjacent", "temperature", {"room": "hallway"}),
        ("solar", "irradiance", {"orientation": "W"}),
        ("prescribed", "flux", {"label": "HVAC"}),
    ],
)
def test_signal_each_role_kind_roundtrip(role, kind, meta):
    """Every valid role/kind combination survives a serialisation round-trip."""
    doc = RoomDoc(uid="sig_rt")
    sig = Signal(id="s0", name=f"{role}_{kind}", kind=kind, role=role, meta=meta)
    doc.signals["s0"] = sig
    doc._signal_counter = 1

    d = roomdoc_to_dict(doc)
    restored = roomdoc_from_dict(d)

    s = restored.signals["s0"]
    assert s.id == "s0"
    assert s.kind == kind
    assert s.role == role
    assert s.meta == meta


def test_signal_to_out_shape():
    """signal_to_out produces a SignalOut with all fields populated."""
    sig = Signal(
        id="s7",
        name="Q_hvac",
        kind="flux",
        role="prescribed",
        meta={"units": "W"},
    )
    out = signal_to_out(sig)
    assert out.id == "s7"
    assert out.name == "Q_hvac"
    assert out.kind == "flux"
    assert out.role == "prescribed"
    assert out.meta == {"units": "W"}


# ── 3. Signal counter mechanics ───────────────────────────────────────────────


def test_next_signal_id_sequence():
    """next_signal_id() yields s0, s1, s2, … in order."""
    doc = RoomDoc()
    assert doc.next_signal_id() == "s0"
    assert doc.next_signal_id() == "s1"
    assert doc.next_signal_id() == "s2"
    assert doc._signal_counter == 3


def test_signal_counter_recovers_from_missing():
    """
    When _signal_counter is absent from the dict (old JSON / example shape),
    the counter falls back to max-numeric-suffix + 1 of existing s… ids.
    """
    d = {
        "uid": "fallback",
        "name": "Test",
        "elements": {},
        "modules": {},
        "routes": {},
        "signals": {
            "s0": {"name": "T_ext", "kind": "temperature", "role": "exterior", "meta": {}},
            "s4": {"name": "G_sol_S", "kind": "irradiance", "role": "solar", "meta": {}},
        },
        # No _signal_counter key.
    }
    doc = roomdoc_from_dict(d)
    # max suffix is 4, so counter must be 5.
    assert doc._signal_counter == 5
    # Next id must not collide.
    new_id = doc.next_signal_id()
    assert new_id == "s5"
    assert new_id not in d["signals"]


def test_signal_counter_recovers_from_empty_signals():
    """When signals is empty and counter absent, counter defaults to 0."""
    d = {
        "uid": "empty",
        "name": "Empty",
        "elements": {},
        "modules": {},
        "routes": {},
        "signals": {},
    }
    doc = roomdoc_from_dict(d)
    assert doc._signal_counter == 0
    assert doc.next_signal_id() == "s0"


def test_signal_counter_explicit_beats_fallback():
    """When _signal_counter is present in the dict, it wins over the fallback."""
    d = {
        "uid": "explicit",
        "name": "Explicit",
        "elements": {},
        "modules": {},
        "routes": {},
        "signals": {
            "s0": {"name": "T_ext", "kind": "temperature", "role": "exterior", "meta": {}},
        },
        "_signal_counter": 10,  # explicitly stored
    }
    doc = roomdoc_from_dict(d)
    assert doc._signal_counter == 10
    assert doc.next_signal_id() == "s10"


# ── 4. New element field construction ────────────────────────────────────────


def test_partition_adjacent_field():
    """Partition accepts an adjacent room label and stores it."""
    p = Partition(
        area=8.0,
        layers=[Layer(material="insulation_mineral_wool", thickness=0.1)],
        adjacent="kitchen",
    )
    assert p.adjacent == "kitchen"


def test_partition_adjacent_defaults_empty():
    """Partition.adjacent defaults to '' when not provided."""
    p = Partition(
        area=8.0,
        layers=[Layer(material="insulation_mineral_wool", thickness=0.1)],
    )
    assert p.adjacent == ""


def test_floor_adjacent_room_field():
    """Floor accepts adjacent_room when boundary=='adjacent'."""
    f = Floor(
        area=20.0,
        boundary="adjacent",
        layers=[Layer(material="concrete_normal", thickness=0.2)],
        adjacent_room="basement",
    )
    assert f.adjacent_room == "basement"


def test_floor_adjacent_room_defaults_empty():
    """Floor.adjacent_room defaults to '' when not provided."""
    f = Floor(
        area=20.0,
        boundary="ground",
        layers=[Layer(material="concrete_normal", thickness=0.2)],
    )
    assert f.adjacent_room == ""


def test_outerwall_treatment_field():
    """OuterWall accepts a treatment override ('simple_loss')."""
    w = OuterWall(
        area=12.0,
        orientation="S",
        layers=[Layer(material="concrete_normal", thickness=0.2)],
        treatment="simple_loss",
    )
    assert w.treatment == "simple_loss"


def test_outerwall_treatment_defaults_empty():
    """OuterWall.treatment defaults to '' (forced default)."""
    w = OuterWall(
        area=10.0,
        orientation="N",
        layers=[Layer(material="insulation_mineral_wool", thickness=0.1)],
    )
    assert w.treatment == ""


# ── 5. Registry exposes boundary + treatments ──────────────────────────────────


def test_registry_has_boundary_and_treatments(client):
    """GET /registry returns boundary and treatments for every element type."""
    r = client.get("/api/registry")
    assert r.status_code == 200
    data = r.json()

    type_map = {et["type_name"]: et for et in data["element_types"]}

    # Every element type must have both keys.
    for tname in ("OuterWall", "Window", "Floor", "Partition", "IndoorMass", "HeatSource"):
        assert tname in type_map, f"{tname} missing from registry"
        et = type_map[tname]
        assert "boundary" in et, f"{tname} missing 'boundary'"
        assert "treatments" in et, f"{tname} missing 'treatments'"


def test_registry_outerwall_treatments_two_entries(client):
    """OuterWall.treatments has exactly the thermal_mass + simple_loss menu."""
    r = client.get("/api/registry")
    assert r.status_code == 200
    type_map = {et["type_name"]: et for et in r.json()["element_types"]}

    treatments = type_map["OuterWall"]["treatments"]
    assert len(treatments) == 2

    keys = {t["key"] for t in treatments}
    assert "thermal_mass" in keys
    assert "simple_loss" in keys

    defaults = {t["key"]: t["default"] for t in treatments}
    assert defaults["thermal_mass"] is True
    assert defaults["simple_loss"] is False


@pytest.mark.parametrize(
    "tname",
    ["Window", "Floor", "Partition", "IndoorMass", "HeatSource"],
)
def test_registry_non_outerwall_treatments_empty(client, tname):
    """All element types except OuterWall have treatments=[]."""
    r = client.get("/api/registry")
    assert r.status_code == 200
    type_map = {et["type_name"]: et for et in r.json()["element_types"]}
    assert type_map[tname]["treatments"] == []


def test_registry_outerwall_boundary_descriptor(client):
    """OuterWall.boundary is {field: 'orientation', role: 'exterior'}."""
    r = client.get("/api/registry")
    type_map = {et["type_name"]: et for et in r.json()["element_types"]}
    assert type_map["OuterWall"]["boundary"] == {"field": "orientation", "role": "exterior"}


def test_registry_indoormass_boundary_none(client):
    """IndoorMass.boundary is null (interior element, no boundary signal)."""
    r = client.get("/api/registry")
    type_map = {et["type_name"]: et for et in r.json()["element_types"]}
    assert type_map["IndoorMass"]["boundary"] is None


def test_registry_partition_boundary_descriptor(client):
    """Partition.boundary is {field: 'adjacent', role: 'adjacent'}."""
    r = client.get("/api/registry")
    type_map = {et["type_name"]: et for et in r.json()["element_types"]}
    assert type_map["Partition"]["boundary"] == {"field": "adjacent", "role": "adjacent"}


def test_registry_partition_has_adjacent_field(client):
    """Partition fields schema includes the new 'adjacent' field."""
    r = client.get("/api/registry")
    type_map = {et["type_name"]: et for et in r.json()["element_types"]}
    field_names = {f["name"] for f in type_map["Partition"]["fields"]}
    assert "adjacent" in field_names


def test_registry_floor_has_adjacent_room_field(client):
    """Floor fields schema includes the new 'adjacent_room' field."""
    r = client.get("/api/registry")
    type_map = {et["type_name"]: et for et in r.json()["element_types"]}
    field_names = {f["name"] for f in type_map["Floor"]["fields"]}
    assert "adjacent_room" in field_names


def test_registry_outerwall_has_treatment_field(client):
    """OuterWall fields schema includes the 'treatment' field."""
    r = client.get("/api/registry")
    type_map = {et["type_name"]: et for et in r.json()["element_types"]}
    field_names = {f["name"] for f in type_map["OuterWall"]["fields"]}
    assert "treatment" in field_names


# ── 6. Regression: examples still load; /document returns signals ─────────────


def test_document_empty_returns_signals_key(client):
    """GET /document on an empty model includes a signals list (may be empty)."""
    r = client.get(f"{BASE}/document")
    assert r.status_code == 200
    data = r.json()
    assert "signals" in data
    assert isinstance(data["signals"], list)
    assert data["signals"] == []  # no signals authored in D1


def test_document_includes_elements_and_modules(client):
    """GET /document still returns elements and modules (routing intact)."""
    # Add an element.
    r = client.post(
        f"{BASE}/elements",
        json={"type": "Window", "fields": {"area": 4.0, "orientation": "S", "U": 1.2, "shgc": 0.6}},
    )
    assert r.status_code == 201
    eid = r.json()["id"]

    # Add a module and route it.
    r = client.post(f"{BASE}/modules", json={"type": "DirectLoss", "fields": {}})
    assert r.status_code == 201
    mid = r.json()["id"]
    client.put(f"{BASE}/modules/{mid}/routing", json={"element_ids": [eid]})

    r = client.get(f"{BASE}/document")
    assert r.status_code == 200
    data = r.json()

    # All three collections present.
    assert "elements" in data
    assert "modules" in data
    assert "signals" in data

    # Content correct.
    assert any(e["id"] == eid for e in data["elements"])
    assert any(m["id"] == mid for m in data["modules"])
    assert any(m["element_ids"] == [eid] for m in data["modules"])


def test_examples_still_load_via_roundtrip():
    """
    Each canonical example loads through roomdoc_from_dict / roomdoc_to_dict
    without error; the result has elements + modules (signals starts empty).
    """
    from thnodes.examples import list_examples, load_example

    for meta in list_examples():
        key = meta["key"]
        raw = load_example(key)
        doc = roomdoc_from_dict(raw)

        # Must have elements and modules.
        assert doc.elements, f"[{key}] no elements"
        assert doc.modules, f"[{key}] no modules"

        # signals starts empty (examples predate D1).
        assert doc.signals == {}, f"[{key}] expected no signals in example"

        # Full round-trip must also succeed.
        serialised = roomdoc_to_dict(doc)
        restored = roomdoc_from_dict(serialised)
        assert set(restored.elements.keys()) == set(doc.elements.keys())
        assert set(restored.modules.keys()) == set(doc.modules.keys())
        # signals key present in serialised form.
        assert "signals" in serialised
        assert serialised["signals"] == {}


def test_document_with_signal_in_store(client):
    """
    When the in-memory doc has a signal, GET /document includes it with the
    correct shape.
    """
    # Directly seed a signal in the default doc (D1 has no signal-creation endpoint).
    doc = _store["default"]
    doc.signals["s0"] = Signal(
        id="s0",
        name="T_ext",
        kind="temperature",
        role="exterior",
        meta={},
    )

    r = client.get(f"{BASE}/document")
    assert r.status_code == 200
    signals = r.json()["signals"]

    assert len(signals) == 1
    s = signals[0]
    assert s["id"] == "s0"
    assert s["name"] == "T_ext"
    assert s["kind"] == "temperature"
    assert s["role"] == "exterior"
    assert s["meta"] == {}
