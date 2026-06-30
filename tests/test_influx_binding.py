"""
Tests for InfluxDB signal-binding (Phase D / InfluxDB integration).

Structure
---------
Hermetic tests (no DB required):
  1. Binding round-trip: Signal.binding persists through roomdoc_to_dict /
     roomdoc_from_dict; absent in old JSON → None.
  2. Grouping-ignores-binding invariant: two docs differing ONLY in a signal's
     binding produce identical GroupResult output.
  3. parse_signal validation: the PUT endpoint returns 400 on a malformed
     binding string.
  4. simulate-bound unbound-signal error path: 400 listing the missing signals.
  5. PUT /signals/{name}/binding sets, updates, and clears the binding;
     persists to disk; returns the updated SignalOut.
  6. GET /document and GET /assembly surface the binding in SignalOut.

Live smoke test (marked, skipped when DB unreachable):
  - GET /influx/signals returns a non-empty list.
  - fetch_series over a recent 2-day window returns a non-empty pd.Series.
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
    binding_map_from_doc,
    roomdoc_from_dict,
    roomdoc_to_dict,
    save_model,
    set_signal_binding,
)
from thnodes.api.models import RoomDoc, Signal, ElementSpec


# ── fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_store():
    """Isolate each test: clear _store and seed a bare default doc."""
    _store.clear()
    _store["default"] = RoomDoc()
    yield
    _store.clear()
    _store["default"] = RoomDoc()


@pytest.fixture
def tmp_data(tmp_path: pathlib.Path, monkeypatch):
    """Redirect USER_DATA_DIR to a fresh temp directory and clear _store."""
    data_dir = tmp_path / "user_data"
    data_dir.mkdir()
    monkeypatch.setattr(store_module, "USER_DATA_DIR", data_dir)
    _store.clear()
    yield data_dir
    _store.clear()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client_with_tmp(tmp_data):
    _store.clear()
    with TestClient(app) as c:
        yield c


BASE = "/api/models/default"

LIGHT_WALL_FIELDS = {
    "area": 10.0,
    "orientation": "S",
    "layers": [{"material": "insulation_mineral_wool", "thickness": 0.1}],
    "alpha": 0.6,
    "treatment": "",
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


def _build_caravan(client):
    """Build the minimal caravan (IndoorMass + light S wall + S window)."""
    _add_element(client, "IndoorMass", INDOOR_MASS_FIELDS)
    _add_element(client, "OuterWall", LIGHT_WALL_FIELDS)
    _add_element(client, "Window", WINDOW_FIELDS)


# ── 1. Binding round-trip ─────────────────────────────────────────────────────

def test_binding_round_trips_through_dict():
    """A stored Signal with binding survives roomdoc_to_dict / roomdoc_from_dict."""
    doc = RoomDoc(uid="rt1", name="Binding RT")
    doc.signals["s0"] = Signal(
        id="s0",
        name="T_ext",
        kind="temperature",
        role="exterior",
        binding="daikin_aircon/inside_temperature?name=Salon",
    )
    d = roomdoc_to_dict(doc)
    # The binding must appear in the serialised form.
    assert d["signals"]["s0"]["binding"] == "daikin_aircon/inside_temperature?name=Salon"

    doc2 = roomdoc_from_dict(d)
    assert doc2.signals["s0"].binding == "daikin_aircon/inside_temperature?name=Salon"


def test_binding_absent_in_old_json_defaults_to_none():
    """Old JSON without a 'binding' key round-trips to None (forward compat)."""
    old_json = {
        "uid": "old",
        "name": "Old",
        "signals": {
            "s0": {"name": "T_ext", "kind": "temperature", "role": "exterior", "meta": {}}
        },
        "_elem_counter": 0,
        "_signal_counter": 1,
    }
    doc = roomdoc_from_dict(old_json)
    assert doc.signals["s0"].binding is None


def test_binding_none_omitted_from_json():
    """A None binding is omitted from the serialised JSON to keep it compact."""
    doc = RoomDoc(uid="rt2", name="No Binding")
    doc.signals["s0"] = Signal(id="s0", name="T_ext", kind="temperature", role="exterior")
    d = roomdoc_to_dict(doc)
    assert "binding" not in d["signals"]["s0"]


def test_set_signal_binding_updates_existing_entry():
    """set_signal_binding updates an existing doc.signals entry in place."""
    doc = RoomDoc(uid="sb")
    doc.signals["s0"] = Signal(id="s0", name="T_ext", kind="temperature", role="exterior")
    set_signal_binding(doc, "T_ext", "open_meteo/temperature_2m")
    assert doc.signals["s0"].binding == "open_meteo/temperature_2m"


def test_set_signal_binding_creates_stub_when_absent():
    """set_signal_binding creates a stub entry when no matching Signal exists."""
    doc = RoomDoc(uid="sb2")
    set_signal_binding(doc, "G_sol_S", "poa/irradiance?face=S")
    found = next((s for s in doc.signals.values() if s.name == "G_sol_S"), None)
    assert found is not None
    assert found.binding == "poa/irradiance?face=S"


def test_set_signal_binding_clears_with_none():
    """set_signal_binding(…, None) clears the binding."""
    doc = RoomDoc(uid="sb3")
    doc.signals["s0"] = Signal(
        id="s0", name="T_ext", kind="temperature", role="exterior",
        binding="open_meteo/temperature_2m",
    )
    set_signal_binding(doc, "T_ext", None)
    assert doc.signals["s0"].binding is None


def test_binding_map_from_doc_only_bound():
    """binding_map_from_doc returns only signals with a non-None binding."""
    doc = RoomDoc(uid="bm")
    doc.signals["s0"] = Signal(id="s0", name="T_ext", kind="temperature", role="exterior",
                               binding="open_meteo/temperature_2m")
    doc.signals["s1"] = Signal(id="s1", name="G_sol_S", kind="irradiance", role="solar")
    bmap = binding_map_from_doc(doc)
    assert bmap == {"T_ext": "open_meteo/temperature_2m"}
    assert "G_sol_S" not in bmap


# ── 2. Grouping-ignores-binding invariant ─────────────────────────────────────

def test_grouping_ignores_binding():
    """
    Two RoomDocs that differ ONLY in a signal's binding produce identical
    GroupResult output (same derived modules, same derived signal names).
    """
    from thnodes.api.store import doc_to_group
    from thnodes.elements import OuterWall, Window, IndoorMass, Layer

    light = Layer("insulation_mineral_wool", 0.1)

    def _build_doc(binding_value):
        doc = RoomDoc(uid="g" + str(hash(binding_value)))
        doc.elements["e0"] = ElementSpec(
            type="IndoorMass", fields={"a": 5.0, "b": 4.0, "c": 2.5, "furniture": "normal"}
        )
        doc.elements["e1"] = ElementSpec(
            type="OuterWall",
            fields={"area": 10.0, "orientation": "S",
                    "layers": [{"material": "insulation_mineral_wool", "thickness": 0.1}],
                    "alpha": 0.6, "treatment": ""},
        )
        doc.elements["e2"] = ElementSpec(
            type="Window",
            fields={"area": 4.0, "orientation": "S", "U": 1.2, "shgc": 0.6},
        )
        # Add a signal with a binding — grouping must not see this.
        doc.signals["s0"] = Signal(
            id="s0", name="T_ext", kind="temperature", role="exterior",
            binding=binding_value,
        )
        return doc

    doc_unbound = _build_doc(None)
    doc_bound = _build_doc("open_meteo/temperature_2m")

    gr_unbound = doc_to_group(doc_unbound)
    gr_bound = doc_to_group(doc_bound)

    # Derived module keys must be identical.
    keys_unbound = {dm.key for dm in gr_unbound.derived_modules}
    keys_bound = {dm.key for dm in gr_bound.derived_modules}
    assert keys_unbound == keys_bound

    # Derived signal names must be identical.
    names_unbound = {s.name for s in gr_unbound.signals}
    names_bound = {s.name for s in gr_bound.signals}
    assert names_unbound == names_bound


# ── 3. parse_signal validation via PUT endpoint ────────────────────────────────

def test_put_binding_malformed_returns_400(client):
    """PUT /signals/{name}/binding with a bad string returns 400."""
    _build_caravan(client)
    # "T_ext" is a required signal for the caravan model.
    r = client.put(
        f"{BASE}/signals/T_ext/binding",
        json={"binding": "no_slash_here"},
    )
    assert r.status_code == 400
    assert "measurement/field" in r.json()["detail"]


def test_put_binding_unknown_signal_returns_404(client):
    """PUT /signals/{name}/binding returns 404 for a non-derived signal name."""
    _build_caravan(client)
    r = client.put(
        f"{BASE}/signals/T_does_not_exist/binding",
        json={"binding": "open_meteo/temperature_2m"},
    )
    assert r.status_code == 404


def test_put_binding_valid_sets_binding(client):
    """PUT /signals/{name}/binding with a valid string sets and returns it."""
    _build_caravan(client)
    r = client.put(
        f"{BASE}/signals/T_ext/binding",
        json={"binding": "open_meteo/temperature_2m"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "T_ext"
    assert data["binding"] == "open_meteo/temperature_2m"


def test_put_binding_null_clears_binding(client):
    """PUT /signals/{name}/binding with null clears a previously set binding."""
    _build_caravan(client)
    # First set it.
    client.put(f"{BASE}/signals/T_ext/binding", json={"binding": "open_meteo/temperature_2m"})
    # Then clear it.
    r = client.put(f"{BASE}/signals/T_ext/binding", json={"binding": None})
    assert r.status_code == 200
    assert r.json()["binding"] is None


def test_put_binding_persists_to_disk(client_with_tmp, tmp_data):
    """After PUT binding, save_model writes binding to disk; reload recovers it."""
    from thnodes.api.store import load_all_models

    uid_r = client_with_tmp.post("/api/models", json={"name": "BindTest"})
    uid = uid_r.json()["uid"]

    # Add elements so T_ext exists as a derived signal.
    client_with_tmp.post(f"/api/models/{uid}/elements",
                         json={"type": "IndoorMass", "fields": INDOOR_MASS_FIELDS})
    client_with_tmp.post(f"/api/models/{uid}/elements",
                         json={"type": "OuterWall", "fields": LIGHT_WALL_FIELDS})
    client_with_tmp.post(f"/api/models/{uid}/elements",
                         json={"type": "Window", "fields": WINDOW_FIELDS})

    # Set a binding.
    r = client_with_tmp.put(
        f"/api/models/{uid}/signals/T_ext/binding",
        json={"binding": "open_meteo/temperature_2m"},
    )
    assert r.status_code == 200

    # Simulate a server restart: reload from disk.
    _store.clear()
    load_all_models()
    doc = _store.get(uid)
    assert doc is not None
    bmap = binding_map_from_doc(doc)
    assert bmap.get("T_ext") == "open_meteo/temperature_2m"


# ── 4. simulate-bound unbound-signal error path ───────────────────────────────

def test_simulate_bound_unbound_returns_400(client):
    """
    POST /simulate-bound on a model with unbound required signals returns 400
    listing the unbound signal names.
    """
    _build_caravan(client)
    r = client.post(
        f"{BASE}/simulate-bound",
        json={"start": "2024-01-01T00:00:00", "end": "2024-01-03T00:00:00"},
    )
    assert r.status_code == 400
    detail = r.json()["detail"]
    # Should mention at least one unbound signal name.
    assert "T_ext" in detail or "G_sol_S" in detail
    assert "binding" in detail.lower()


def test_simulate_bound_incomplete_room_returns_400(client):
    """simulate-bound with an incomplete room (no IndoorMass) returns 400."""
    _add_element(client, "OuterWall", LIGHT_WALL_FIELDS)
    r = client.post(
        f"{BASE}/simulate-bound",
        json={"start": "2024-01-01T00:00:00", "end": "2024-01-03T00:00:00"},
    )
    assert r.status_code == 400
    assert "incomplete" in r.json()["detail"].lower()


# ── 5. GET /document and /assembly surface binding ────────────────────────────

def test_document_signals_include_binding(client):
    """
    After a PUT binding, GET /document signals list includes the binding on the
    relevant SignalOut entry.
    """
    _build_caravan(client)
    client.put(
        f"{BASE}/signals/T_ext/binding",
        json={"binding": "open_meteo/temperature_2m"},
    )
    r = client.get(f"{BASE}/document")
    assert r.status_code == 200
    signals = r.json()["signals"]
    t_ext_sig = next((s for s in signals if s["name"] == "T_ext"), None)
    assert t_ext_sig is not None
    assert t_ext_sig["binding"] == "open_meteo/temperature_2m"


def test_document_signals_unbound_is_null(client):
    """
    Unbound signals in GET /document have binding=null (not absent).
    """
    _build_caravan(client)
    r = client.get(f"{BASE}/document")
    signals = r.json()["signals"]
    for sig in signals:
        assert "binding" in sig, f"Signal {sig['name']} missing 'binding' key"
        assert sig["binding"] is None


def test_assembly_required_signals_include_binding(client):
    """
    After a PUT binding, GET /assembly required_signals includes the binding.
    """
    _build_caravan(client)
    client.put(
        f"{BASE}/signals/T_ext/binding",
        json={"binding": "open_meteo/temperature_2m"},
    )
    r = client.get(f"{BASE}/assembly")
    assert r.status_code == 200
    req_sigs = r.json()["required_signals"]
    t_ext_sig = next((s for s in req_sigs if s["name"] == "T_ext"), None)
    assert t_ext_sig is not None
    assert t_ext_sig["binding"] == "open_meteo/temperature_2m"


# ── 6. GET /influx/signals (mocked) ───────────────────────────────────────────

def test_get_influx_signals_db_unreachable_returns_503(client, monkeypatch):
    """
    When the InfluxDB client raises an exception, GET /influx/signals returns 503.
    """
    import thnodes.api.routes.influx as route_mod
    import thnodes.data_src.influx as influx_mod

    original_list_signals = influx_mod.list_signals

    def _boom(client=None):
        raise ConnectionRefusedError("DB is down")

    # Patch the _influx module object held by the route module.
    monkeypatch.setattr(route_mod._influx, "list_signals", _boom)
    r = client.get("/api/influx/signals")
    assert r.status_code == 503
    assert "unreachable" in r.json()["detail"].lower()


def test_get_influx_signals_returns_list(client, monkeypatch):
    """
    When list_signals returns data, GET /influx/signals proxies the list.
    """
    import thnodes.api.routes.influx as route_mod

    fake_signals = ["open_meteo/temperature_2m", "daikin_aircon/inside_temperature?name=Salon"]
    monkeypatch.setattr(route_mod._influx, "list_signals", lambda client=None: fake_signals)

    r = client.get("/api/influx/signals")
    assert r.status_code == 200
    assert r.json() == fake_signals


# ── 7. simulate-bound with mocked DB ─────────────────────────────────────────

def test_simulate_bound_with_mocked_db(client, monkeypatch):
    """
    simulate-bound succeeds when all required signals are bound and
    fetch_series returns sensible data.
    """
    import pandas as pd
    import thnodes.api.routes.influx as route_mod

    _build_caravan(client)

    # Bind both required signals (T_ext and G_sol_S).
    client.put(f"{BASE}/signals/T_ext/binding",
               json={"binding": "open_meteo/temperature_2m"})
    client.put(f"{BASE}/signals/G_sol_S/binding",
               json={"binding": "poa/irradiance?face=S"})

    # Fake fetch_series: returns 10 steps at 15-min intervals.
    idx = pd.date_range("2024-01-01", periods=10, freq="15min", tz="UTC")

    def _fake_fetch(signal, start, end, resample="15min", client=None):
        name_map = {
            "open_meteo/temperature_2m": 5.0,
            "poa/irradiance?face=S": 100.0,
        }
        val = name_map.get(signal, 0.0)
        return pd.Series([val] * 10, index=idx, name=signal)

    # Patch via the _influx module object held by the route module.
    monkeypatch.setattr(route_mod._influx, "fetch_series", _fake_fetch)

    r = client.post(
        f"{BASE}/simulate-bound",
        json={"start": "2024-01-01T00:00:00", "end": "2024-01-01T02:30:00"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "t" in data
    assert "states" in data
    assert "T_room" in data["states"]
    assert len(data["t"]) == 10


# ── Live smoke test (skip when DB unreachable) ─────────────────────────────────

def _is_db_reachable() -> bool:
    """Return True if the InfluxDB configured in .env/environment is reachable."""
    try:
        from thnodes.data_src.influx import _make_client
        c = _make_client()
        c.ping()
        return True
    except Exception:
        return False


_DB_AVAILABLE = _is_db_reachable()

@pytest.mark.skipif(not _DB_AVAILABLE, reason="InfluxDB not reachable from this environment")
def test_live_list_signals():
    """GET /api/influx/signals returns a non-empty list from the real DB."""
    from thnodes.data_src.influx import list_signals
    sigs = list_signals()
    assert len(sigs) > 0, "Expected at least one signal from the live DB"
    # Spot-check that names follow the expected format.
    for sig in sigs[:5]:
        assert "/" in sig, f"Signal format unexpected: {sig!r}"


@pytest.mark.skipif(not _DB_AVAILABLE, reason="InfluxDB not reachable from this environment")
def test_live_fetch_series():
    """
    fetch_series over a recent 2-day window for the Daikin Salon temperature
    signal returns a non-empty pd.Series.

    We discover the exact canonical signal name via list_signals() first
    (InfluxDB v1 returns all tag keys, so the name is e.g.
    ``daikin_aircon/inside_temperature?mac=C0E434E63752&name=Salon&type=aircon``).
    The date range is chosen from recent data available in the DB (around
    2026-05-27, the last-known timestamp); we do a wider search around the
    most-recent data point.
    """
    import pandas as pd
    from thnodes.data_src.influx import list_signals, fetch_series, _make_client

    sigs = list_signals()

    # Find any "inside_temperature" signal for "Salon" in the Daikin measurement.
    target = next(
        (s for s in sigs if "inside_temperature" in s and "Salon" in s and "daikin_aircon" in s),
        None,
    )
    if target is None:
        # Fallback: any temperature-looking signal.
        target = next((s for s in sigs if "temperature" in s.lower()), sigs[0])

    # Discover the most recent data point to build a valid date range.
    c = _make_client()
    meas = target.split("/")[0]
    field = target.split("/")[1].split("?")[0]
    last_result = c.query(f'SELECT last("{field}") FROM "{meas}"')
    if last_result:
        last_df = next(iter(last_result.values()))
        last_ts = str(last_df.index[0])[:10]  # "YYYY-MM-DD"
        # Fetch 2 days ending at the last timestamp + 1 day.
        import datetime
        end_dt = datetime.datetime.fromisoformat(last_ts) + datetime.timedelta(days=1)
        start_dt = end_dt - datetime.timedelta(days=2)
        start_str = start_dt.strftime("%Y-%m-%dT00:00:00Z")
        end_str = end_dt.strftime("%Y-%m-%dT00:00:00Z")
    else:
        start_str = "2026-05-26T00:00:00Z"
        end_str = "2026-05-28T00:00:00Z"

    s = fetch_series(target, start_str, end_str, resample="15min")
    assert isinstance(s, pd.Series)
    assert len(s) > 0, (
        f"Expected non-empty series for {target!r} in [{start_str}, {end_str})"
    )
    assert s.dtype.kind == "f", "Expected float dtype"
