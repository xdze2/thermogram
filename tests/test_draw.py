"""
Stage 4 — topology rendering tests.

Two layers, matching draw.py:

  1. The graph IR (`topology`) — structural assertions that the assembled module list maps
     to the right nodes / conductances / fluxes. Pure, no schemdraw. This is where the
     "schematic matches the module list" guarantee lives.
  2. `render` — a smoke test that the IR draws to non-empty SVG bytes (native backend, no
     matplotlib).
"""

import json
from pathlib import Path

import pytest

from thermal.api_models import Room
from thermal.draw import topology, render
from thermal.simulate import AGG_WALL_NODE
from thermal import modules as M

FIXTURES = Path(__file__).parent / "fixtures"


def load_room(name: str) -> Room:
    return Room(**json.loads((FIXTURES / f"{name}.json").read_text()))


def _edges(topo):
    return {(c.a, c.b, c.h_label) for c in topo.conductances}


# ---------------------------------------------------------------------------
# 1. IR structure — the schematic matches the module list
# ---------------------------------------------------------------------------

def test_heavy_room_is_2r2c():
    """house: one aggregated wall node, the canonical 2R2C edges, one Q_room flux."""
    topo = topology(load_room("house"))

    assert {n.key for n in topo.nodes} == {M.ROOM_NODE, AGG_WALL_NODE}
    assert _edges(topo) == {
        (AGG_WALL_NODE, "T_sa", "$H_{env}$"),   # sol-air into the wall mass
        (AGG_WALL_NODE, M.ROOM_NODE, "$H_{int}$"),  # wall mass into the room
        (M.ROOM_NODE, "T_ext", "$H_{ve}$"),     # ventilation + window conduction
    }
    assert [(f.node, f.source) for f in topo.fluxes] == [(M.ROOM_NODE, "Q_room")]


def test_aggregation_collapses_parallel_walls():
    """Six heavy walls aggregate to a single wall node + single H_env/H_int edge."""
    topo = topology(load_room("house"), aggregate=True)
    wall_edges = [c for c in topo.conductances if c.a == AGG_WALL_NODE]
    # one source coupling (H_env) + one node coupling (H_int), not six of each
    assert len(wall_edges) == 2


def test_per_element_keeps_distinct_wall_nodes():
    """aggregate=False keeps one mass node per heavy wall (granularity choice)."""
    agg = topology(load_room("house"), aggregate=True)
    per = topology(load_room("house"), aggregate=False)
    assert len([n for n in agg.nodes if n.key != M.ROOM_NODE]) == 1
    assert len([n for n in per.nodes if n.key != M.ROOM_NODE]) > 1


def test_caravan_degrades_to_single_node():
    """caravan: no STORAGE → no wall node; light walls conduct T_sa→room directly."""
    topo = topology(load_room("caravan"))

    assert {n.key for n in topo.nodes} == {M.ROOM_NODE}
    assert _edges(topo) == {
        (M.ROOM_NODE, "T_sa", "$H_{env}$"),   # light walls, direct (no mass)
        (M.ROOM_NODE, "T_ext", "$H_{ve}$"),   # ventilation
    }


def test_module_names_recorded():
    topo = topology(load_room("house"))
    assert "RoomMass" in topo.module_names
    assert "HeavyWall" in topo.module_names
    assert "SolarGain" in topo.module_names


# ---------------------------------------------------------------------------
# 2. render — draws to SVG bytes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["caravan", "house", "passive"])
def test_render_svg_nonempty(name):
    svg = render(topology(load_room(name)), fmt="svg")
    assert svg[:4] == b"<svg"
    assert len(svg) > 500
