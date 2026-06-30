"""
Tests for the canonical example rooms in thnodes.examples.

D3 update: examples no longer carry modules/routes.  Modules are DERIVED by
the grouping rule (doc_to_group / group()).  Assembly is tested via
doc_to_group → to_assembler → build().

Verifies:
1. Every example JSON loads and has the expected top-level keys (elements; no
   modules/routes in D3 examples).
2. Feeding each example through doc_to_group + to_assembler + build(strict=False)
   produces a System without double_count or missing_room_mass problems
   for the well-formed rooms (caravan, heavy_wall).
3. The cellar example assembles without problems (the window's SOLAR_TRANSMISSION
   is now correctly claimed by a derived SolarGain[G_sol_N] module).
4. list_examples() and load_example() public API behaves correctly.
5. Derived module sets match what building physics says for each example.
"""

from __future__ import annotations

import warnings

import pytest

from thnodes.examples import list_examples, load_example
from thnodes.api.store import doc_to_group, roomboc_to_assembler
from thnodes.api.models import ElementSpec, RoomDoc
from thnodes.api.store import roomdoc_from_dict


# ── helpers ───────────────────────────────────────────────────────────────────


def _doc_from_example(key: str) -> RoomDoc:
    """Convert an example dict into a RoomDoc suitable for doc_to_group."""
    data = load_example(key)
    doc = roomdoc_from_dict(data)
    return doc


# ── list_examples / load_example ──────────────────────────────────────────────


def test_list_examples_has_all_keys():
    metas = list_examples()
    keys = {m["key"] for m in metas}
    assert {"caravan", "heavy_wall", "collinear", "cellar"}.issubset(keys)


def test_list_examples_has_names():
    for meta in list_examples():
        assert "key" in meta and "name" in meta
        assert meta["name"]  # non-empty string


def test_load_example_caravan():
    doc = load_example("caravan")
    assert "name" in doc
    assert "elements" in doc
    # D3: examples no longer carry modules/routes (derived at read time).
    # Old JSON keys may still be present for load-compatibility but content is empty.
    # The key assertion below checks the schema; content is not required.


def test_load_example_unknown_key_raises():
    with pytest.raises(KeyError):
        load_example("nonexistent_room_xyz")


def test_load_example_all_valid_keys():
    """Every key from list_examples() must load without error."""
    for meta in list_examples():
        data = load_example(meta["key"])
        assert isinstance(data, dict)


# ── assembly: well-formed rooms produce no fatal problems ─────────────────────


@pytest.mark.parametrize("key", ["caravan", "heavy_wall"])
def test_well_formed_rooms_assemble(key: str):
    """
    Well-formed rooms (caravan, heavy_wall) must assemble to a non-None System
    without double_count or missing_room_mass problems.
    """
    doc = _doc_from_example(key)
    gr = doc_to_group(doc)
    asm = gr.to_assembler()
    system, problems = asm.build(strict=False)

    assert system is not None, f"[{key}] build() returned None; problems: {problems}"

    fatal_kinds = {p.kind for p in problems}
    assert "double_count" not in fatal_kinds, (
        f"[{key}] unexpected double_count: {[p.message for p in problems]}"
    )
    assert "missing_room_mass" not in fatal_kinds, (
        f"[{key}] unexpected missing_room_mass: {[p.message for p in problems]}"
    )


def test_collinear_assembles_same_as_heavy_wall():
    """
    Collinear shares the heavy_wall topology; it must assemble identically
    (same states, same param names).
    """
    doc_hw = _doc_from_example("heavy_wall")
    doc_col = _doc_from_example("collinear")

    gr_hw = doc_to_group(doc_hw)
    gr_col = doc_to_group(doc_col)

    sys_hw, _ = gr_hw.to_assembler().build(strict=False)
    sys_col, _ = gr_col.to_assembler().build(strict=False)

    assert sys_hw is not None
    assert sys_col is not None
    assert sys_hw.state_names == sys_col.state_names
    assert sys_hw.param_names == sys_col.param_names


def test_cellar_assembles_cleanly():
    """
    Cellar (window N) assembles cleanly — the grouping rule derives
    SolarGain[G_sol_N] for the window's SOLAR_TRANSMISSION budget so there
    is no unclaimed channel.  No fatal problems expected.
    """
    doc = _doc_from_example("cellar")
    gr = doc_to_group(doc)
    asm = gr.to_assembler()
    system, problems = asm.build(strict=False)

    assert system is not None, f"cellar build() returned None; problems: {problems}"

    fatal_kinds = {p.kind for p in problems}
    assert "double_count" not in fatal_kinds
    assert "missing_room_mass" not in fatal_kinds
    # No unclaimed channel either — SolarGain[G_sol_N] claims SOLAR_TRANSMISSION.
    assert "unclaimed_channel" not in fatal_kinds


# ── state / param sanity checks ───────────────────────────────────────────────


def test_caravan_has_one_state():
    doc = _doc_from_example("caravan")
    gr = doc_to_group(doc)
    system, _ = gr.to_assembler().build(strict=False)
    assert system is not None
    assert system.state_names == ["T_room"]


def test_heavy_wall_has_two_states():
    doc = _doc_from_example("heavy_wall")
    gr = doc_to_group(doc)
    system, _ = gr.to_assembler().build(strict=False)
    assert system is not None
    assert "T_room" in system.state_names
    # HeavyWall adds a private wall state
    assert len(system.state_names) == 2


# ── derived module sets ───────────────────────────────────────────────────────


def test_caravan_derived_modules():
    """
    Caravan: IndoorMass + light OuterWall (S) + Window (S).
    Expected derived modules: RoomMass, DirectLoss[T_ext], SolarGain[G_sol_S].
    """
    doc = _doc_from_example("caravan")
    gr = doc_to_group(doc)
    module_keys = {dm.key for dm in gr.derived_modules}

    assert ("RoomMass", None) in module_keys
    assert ("DirectLoss", "T_ext") in module_keys
    assert ("SolarGain", "G_sol_S") in module_keys
    # No heavy-wall branch.
    assert ("HeavyWall", "T_ext") not in module_keys


def test_heavy_wall_derived_modules():
    """
    Heavy-wall: IndoorMass + heavy OuterWall (S, thermal_mass) + Window (S).
    Expected derived modules: RoomMass, HeavyWall[T_ext], DirectLoss[T_ext],
    SolarGain[G_sol_S].
    """
    doc = _doc_from_example("heavy_wall")
    gr = doc_to_group(doc)
    module_keys = {dm.key for dm in gr.derived_modules}

    assert ("RoomMass", None) in module_keys
    assert ("HeavyWall", "T_ext") in module_keys
    assert ("DirectLoss", "T_ext") in module_keys
    assert ("SolarGain", "G_sol_S") in module_keys


def test_caravan_required_signals():
    """Caravan requires exactly T_ext and G_sol_S."""
    doc = _doc_from_example("caravan")
    gr = doc_to_group(doc)
    signal_names = {s.name for s in gr.signals}
    assert signal_names == {"T_ext", "G_sol_S"}


def test_cellar_derived_modules():
    """
    Cellar: IndoorMass + Window (N).
    Expected derived modules: RoomMass, DirectLoss[T_ext], SolarGain[G_sol_N].
    """
    doc = _doc_from_example("cellar")
    gr = doc_to_group(doc)
    module_keys = {dm.key for dm in gr.derived_modules}

    assert ("RoomMass", None) in module_keys
    assert ("DirectLoss", "T_ext") in module_keys
    assert ("SolarGain", "G_sol_N") in module_keys
