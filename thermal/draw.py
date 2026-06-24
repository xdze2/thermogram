"""
Topology rendering (roadmap Stage 4) — assembled module graph → RC schematic.

This draws the *structure* a room assembles into, not a parameter sample: nodes
(`T_room` plus any wall mass nodes), conductances to driving sources (`T_ext`/`T_sa`),
and prescribed-flux sources (`Q_room`). The labels are the symbolic parameters
(`H_env`, `H_int`, `C_wall`, …), so the same picture serves every parameter draw.

Two layers, mirroring the rest of the engine:

  1. `topology(room)` — walk the assembled modules' `dynamics()` to a small graph IR
     (`Topology`: nodes, conductances, flux sources). Pure, dependency-free, testable.
  2. `render(topo)` — lay the IR out with schemdraw → SVG/PNG bytes (server-side).

schemdraw is imported lazily inside `render` so the IR (and its tests) need no plotting
dependency; only actually drawing pulls it in.

RC ↔ thermal analogy (as in docs/draw_modules.py): R = 1/H, C = thermal mass, a voltage
source = a prescribed boundary temperature, a current source = a prescribed heat flux.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .api_models import Room
from .assembler import assemble
from .simulate import AGG_WALL_NODE
from .state_space import h_int_from_room
from . import modules as M


# Symbolic edge labels — the *topology* carries parameter names, not magnitudes, so one
# schematic stands for the whole prior. Keyed by the sampled-scalar param a coupling reads.
_H_LABEL = {
    "H_env": "$H_{env}$",
    "H_int": "$H_{int}$",
    "H_ve": "$H_{ve}$",
}
_C_LABEL = {
    M.ROOM_NODE: "$C_{room}$",
    AGG_WALL_NODE: "$C_{wall}$",
}

# Pretty source/signal labels for the boundary glyphs.
_SOURCE_LABEL = {
    "T_ext": "$T_{ext}$",
    "T_sa": "$T_{sa}$",
    "Q_room": "$Q_{room}$",
}


# ---------------------------------------------------------------------------
# Graph IR
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TopoNode:
    """A temperature state: the room air, or a wall mass node."""

    key: str          # state-vector key (ROOM_NODE / AGG_WALL_NODE)
    cap_label: str    # symbolic capacitance, e.g. "$C_{wall}$"


@dataclass(frozen=True)
class TopoConductance:
    """A resistor: between two nodes, or from a boundary source into a node."""

    a: str            # node key
    b: str            # the other node key, or a source name (T_ext / T_sa)
    h_label: str      # symbolic conductance, e.g. "$H_{env}$"
    b_is_source: bool


@dataclass(frozen=True)
class TopoFlux:
    """A current source: a prescribed heat flux injected into a node."""

    node: str
    source: str       # signal name (Q_room)
    label: str


@dataclass
class Topology:
    """The drawable structure of an assembled room."""

    nodes: list[TopoNode] = field(default_factory=list)
    conductances: list[TopoConductance] = field(default_factory=list)
    fluxes: list[TopoFlux] = field(default_factory=list)
    module_names: list[str] = field(default_factory=list)

    def node(self, key: str) -> TopoNode | None:
        return next((n for n in self.nodes if n.key == key), None)


# ---------------------------------------------------------------------------
# room → Topology
# ---------------------------------------------------------------------------

# Placeholder params: `dynamics()` needs numbers, but topology only cares which edges
# exist and which signal/param each reads. We tag every magnitude with a sentinel and map
# couplings back to symbolic labels by the param each module reads (see _label_for).
_PARAM = 1.0


def topology(room: Room, aggregate: bool = True) -> Topology:
    """Extract the drawable RC graph from the assembled modules.

    Heavy walls are aggregated into the single `T_wall` 2R2C node by default (the picture
    most users expect); pass `aggregate=False` to keep per-element mass nodes.
    """
    mods = assemble(room)
    h_int_total = h_int_from_room(room)

    opaque = [m for m in mods if isinstance(m, M.HeavyWall)]
    heavy = [m for m in opaque if m.is_heavy]

    topo = Topology(module_names=[type(m).__name__ for m in mods])

    # Each coupling/flux is emitted by a module that reads exactly one of the sampled
    # scalars; we attach the symbolic label by which placeholder magnitude we fed in.
    dyn_list: list[tuple[M.Dynamics, dict[str, str]]] = []

    for m in mods:
        if isinstance(m, M.HeavyWall) and m.is_heavy:
            m.node_key = AGG_WALL_NODE if aggregate else f"T_wall_{m.element.uid}"
            d = m.dynamics({"C_wall": _PARAM, "H_env": _PARAM, "H_int": h_int_total})
            # mass node coupling reads H_int; source coupling reads H_env
            dyn_list.append((d, {"node_coupling": "H_int", "source_coupling": "H_env",
                                 "node": "C_wall"}))
        elif isinstance(m, M.HeavyWall):
            d = m.dynamics({"H_env": _PARAM})
            dyn_list.append((d, {"source_coupling": "H_env"}))
        elif isinstance(m, M.RoomMass):
            d = m.dynamics({"C_room": _PARAM})
            dyn_list.append((d, {"node": "C_room"}))
        else:  # Ventilation, SolarGain, WindowLoss…
            d = m.dynamics({"C_room": _PARAM, "H_ve": _PARAM})
            dyn_list.append((d, {"source_coupling": "H_ve"}))

    _fold(topo, dyn_list, aggregate)
    return topo


def _fold(topo: Topology, dyn_list, aggregate: bool) -> None:
    """Merge the module Dynamics into the IR, deduping edges that collapse onto a node.

    When heavy walls aggregate onto the shared `T_wall` node, their per-element couplings
    land on the *same* node pair — physically a parallel sum (one `H_env`, one `H_int`),
    so the schematic draws a single resistor. We key edges by (a, b) and fluxes by (node,
    signal) and keep one. (For `aggregate=False` the keys differ per wall, so all survive.)
    """
    seen_nodes: set[str] = set()
    for d, _ in dyn_list:
        for n in d.nodes:
            if n.key in seen_nodes:
                continue
            seen_nodes.add(n.key)
            topo.nodes.append(TopoNode(
                key=n.key,
                cap_label=_C_LABEL.get(n.key, "$C$"),
            ))

    seen_edges: set[tuple[str, str]] = set()
    seen_fluxes: set[tuple[str, str]] = set()
    for d, labels in dyn_list:
        for nc in d.node_couplings:
            if (nc.a, nc.b) in seen_edges:
                continue
            seen_edges.add((nc.a, nc.b))
            topo.conductances.append(TopoConductance(
                a=nc.a, b=nc.b,
                h_label=_H_LABEL[labels["node_coupling"]],
                b_is_source=False,
            ))
        for sc in d.source_couplings:
            if (sc.node, sc.signal) in seen_edges:
                continue
            seen_edges.add((sc.node, sc.signal))
            topo.conductances.append(TopoConductance(
                a=sc.node, b=sc.signal,
                h_label=_H_LABEL[labels["source_coupling"]],
                b_is_source=True,
            ))
        for sf in d.source_fluxes:
            if (sf.node, sf.signal) in seen_fluxes:
                continue
            seen_fluxes.add((sf.node, sf.signal))
            topo.fluxes.append(TopoFlux(
                node=sf.node, source=sf.signal,
                label=_SOURCE_LABEL.get(sf.signal, sf.signal),
            ))


# ---------------------------------------------------------------------------
# Topology → schemdraw
# ---------------------------------------------------------------------------

def _node_label(key: str) -> str:
    if key == M.ROOM_NODE:
        return "$T_{room}$"
    if key == AGG_WALL_NODE:
        return "$T_{wall}$"
    return key.replace("T_wall_", "$T_{wall:") + "}$" if key.startswith("T_wall_") else key


def render(topo: Topology, fmt: str = "svg") -> bytes:
    """Lay the topology out with schemdraw and return the image bytes.

    A horizontal spine carries the conductive chain (sources → mass node → room),
    capacitors hang to a common ground datum below each node, and flux sources inject
    from below the room node.

    `fmt` is "svg" (native backend, no matplotlib — the server default) or "png"
    (needs matplotlib).
    """
    import schemdraw
    import schemdraw.elements as elm

    schemdraw.use("matplotlib" if fmt == "png" else "svg")

    room_couplings = [c for c in topo.conductances if not c.b_is_source]
    wall_node = topo.node(AGG_WALL_NODE)

    with schemdraw.Drawing(show=False) as d:
        d.config(unit=2.4, fontsize=13)

        if wall_node is not None:
            # 2R2C chain: T_sa --H_env--> [T_wall] --H_int--> [T_room]
            sa = _spine_source(d, elm, _spine_source_label(topo, AGG_WALL_NODE))
            d.add(elm.Resistor().right().label(_spine_h(topo, AGG_WALL_NODE, source=True), "bottom"))
            d.add(elm.Dot().label(_node_label(AGG_WALL_NODE), "top", ofst=(-0.1, 0.25)))
            d.push()
            d.add(elm.Capacitor().down().length(2.2).label(wall_node.cap_label, "left", ofst=(0, 0.7)))
            d.add(elm.Ground())
            d.pop()
            h_int = next((c.h_label for c in room_couplings), "$H_{int}$")
            d.add(elm.Resistor().right().label(h_int, "bottom"))
            room_dot = d.add(elm.Dot().label(_node_label(M.ROOM_NODE), "top", ofst=(0.15, 0.35)))
            _room_stack(d, elm, topo, room_dot, sa)
        else:
            # Pure-resistive room: light walls feed T_sa→room and T_ext→room directly.
            sa = _spine_source(d, elm, _spine_source_label(topo, M.ROOM_NODE))
            d.add(elm.Resistor().right().label(_spine_h(topo, M.ROOM_NODE, source=True), "bottom"))
            room_dot = d.add(elm.Dot().label(_node_label(M.ROOM_NODE), "top", ofst=(0.15, 0.35)))
            _room_stack(d, elm, topo, room_dot, sa)

        d.add(elm.Label().at((-0.5, 4.0)).label(
            "  +  ".join(_unique(topo.module_names)), "center", fontsize=10, color="navy"))

    return d.get_imagedata(fmt)


def _room_stack(d, elm, topo: Topology, room_dot, spine_src) -> None:
    """C_room to ground, the T_ext source coupling (drawn high), and the flux sources.

    Layout: C_room drops straight to the datum under the room node; the spine source's
    bottom returns to that same datum; H_ve loops well above the spine and comes down to
    the right of the room node; each prescribed flux is a current source further right.
    """
    room_node = topo.node(M.ROOM_NODE)
    d.push()
    d.add(elm.Capacitor().down().length(2.2).label(
        room_node.cap_label if room_node else "$C_{room}$", "right", ofst=(0, 0.7)))
    gnd = d.add(elm.Ground())
    d.pop()
    # close the spine source's return to the datum
    d.add(elm.Line().down().toy(gnd.center).at(spine_src.start))

    # the spine source whose start sits to the *left* — used as the H_ve loop's far end
    ext_couplings = [c for c in topo.conductances
                     if c.b_is_source and c.b == "T_ext" and c.a == M.ROOM_NODE]

    # rightmost x used so flux sources don't collide with the H_ve loop's return leg
    x_cursor = room_dot.center[0]

    # H_ve: from T_ext up and over into the room node, kept clear above the spine.
    for k, c in enumerate(ext_couplings):
        loop_h = 2.0
        d.push()
        top = d.add(elm.Line().up().at(room_dot.center).length(loop_h))
        d.add(elm.Resistor().right().label(c.h_label, "top"))
        src = d.add(elm.SourceV().down().reverse().label(_SOURCE_LABEL.get(c.b, c.b), "right"))
        d.add(elm.Line().down().toy(gnd.center))
        d.add(elm.Line().left().tox(gnd.center))
        d.pop()
        x_cursor = src.start[0]

    # Flux sources (Q_room): current source injecting into the room from the datum.
    for k, f in enumerate(topo.fluxes):
        x_cursor += 2.0
        d.push()
        d.add(elm.Line().right().at(room_dot.center).tox(x_cursor))
        d.add(elm.SourceI().down().label(f.label, "right"))
        d.add(elm.Line().left().tox(gnd.center).toy(gnd.center))
        d.pop()


# --- small label helpers ---------------------------------------------------

def _spine_source(d, elm, label: str):
    src = d.add(elm.SourceV().up().label(label, "left"))
    d.add(elm.Line().right().length(0.7))
    return src


def _spine_coupling(topo: Topology, node_key: str):
    """The source coupling drawn on the horizontal spine into `node_key`.

    Prefer the sol-air drive (`T_sa`) so H_env is the spine and H_ve loops above; fall
    back to whatever source coupling that node has.
    """
    cands = [c for c in topo.conductances if c.b_is_source and c.a == node_key]
    return next((c for c in cands if c.b == "T_sa"), cands[0] if cands else None)


def _spine_source_label(topo: Topology, node_key: str) -> str:
    c = _spine_coupling(topo, node_key)
    return _SOURCE_LABEL.get(c.b, c.b) if c else "$T_{sa}$"


def _spine_h(topo: Topology, node_key: str, source: bool) -> str:
    c = _spine_coupling(topo, node_key)
    return c.h_label if c else "$H_{env}$"


def _unique(seq) -> list[str]:
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
