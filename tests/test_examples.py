"""
Tests for the canonical example rooms in thnodes.examples.

Verifies:
1. Every example JSON loads and has the expected top-level keys.
2. Feeding each example through roomboc_to_assembler + build(strict=False)
   produces a System without double_count or missing_room_mass problems
   for the well-formed rooms (caravan, heavy_wall).
3. The cellar example assembles but may emit an UNCLAIMED_CHANNEL warning
   for SOLAR_TRANSMISSION (documented expected behaviour).
4. list_examples() and load_example() public API behaves correctly.
"""

from __future__ import annotations

import warnings

import pytest

from thnodes.examples import list_examples, load_example
from thnodes.api.store import roomboc_to_assembler
from thnodes.api.models import ElementSpec, ModuleSpec, RoomDoc


# ── helpers ───────────────────────────────────────────────────────────────────


def _doc_from_example(key: str) -> RoomDoc:
    """Convert an example dict into a RoomDoc suitable for roomboc_to_assembler."""
    data = load_example(key)
    doc = RoomDoc()

    for eid, espec in data["elements"].items():
        doc.elements[eid] = ElementSpec(type=espec["type"], fields=espec["fields"])

    for mid, mspec in data["modules"].items():
        doc.modules[mid] = ModuleSpec(type=mspec["type"], fields=mspec["fields"])

    doc.routes = {mid: list(eids) for mid, eids in data.get("routes", {}).items()}
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
    assert "modules" in doc
    assert "routes" in doc


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
    asm = roomboc_to_assembler(doc)
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

    sys_hw, _ = roomboc_to_assembler(doc_hw).build(strict=False)
    sys_col, _ = roomboc_to_assembler(doc_col).build(strict=False)

    assert sys_hw is not None
    assert sys_col is not None
    assert sys_hw.state_names == sys_col.state_names
    assert sys_hw.param_names == sys_col.param_names


def test_cellar_assembles_with_expected_warning():
    """
    Cellar has an unclaimed SOLAR_TRANSMISSION channel (window with no solar
    module).  build(strict=False) must return a non-None System; any problems
    must NOT be double_count or missing_room_mass.
    """
    doc = _doc_from_example("cellar")
    asm = roomboc_to_assembler(doc)

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*[Uu]nclaimed.*SOLAR_TRANSMISSION.*")
        system, problems = asm.build(strict=False)

    assert system is not None, f"cellar build() returned None; problems: {problems}"

    fatal_kinds = {p.kind for p in problems}
    assert "double_count" not in fatal_kinds
    assert "missing_room_mass" not in fatal_kinds


# ── state / param sanity checks ───────────────────────────────────────────────


def test_caravan_has_one_state():
    doc = _doc_from_example("caravan")
    system, _ = roomboc_to_assembler(doc).build(strict=False)
    assert system is not None
    assert system.state_names == ["T_room"]


def test_heavy_wall_has_two_states():
    doc = _doc_from_example("heavy_wall")
    system, _ = roomboc_to_assembler(doc).build(strict=False)
    assert system is not None
    assert "T_room" in system.state_names
    # HeavyWall adds a private wall state
    assert len(system.state_names) == 2
