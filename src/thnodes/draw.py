"""
Rendering layer: turn user-described elements and assembled systems into views.

Two pure outputs, reused by both the Streamlit case notebook and (eventually) the
FastAPI endpoint the proposal describes (server-side topology rendering):

  - elements_table(elements) -> list[dict]    pre-assembly "what did the user describe"
  - topology_svg(system)     -> str (SVG)     post-assembly RC star schematic (schemdraw)

Physics is never recomputed here: the elements table reads each element's own
channels() budgets, and the schematic reads the assembled System's modules.
"""

from __future__ import annotations

from .channels import Budget, Channel
from .elements import EnvelopeElement, Layer
from .assembler import System


# ── elements view (pre-assembly) ─────────────────────────────────────────────


def _layers_str(layers: list[Layer]) -> str:
    return " | ".join(f"{l.material} {l.thickness * 1000:.0f}mm" for l in layers)


def _fmt(x: float | None, unit: str = "") -> str:
    if x is None:
        return "—"
    return f"{x:.3g} {unit}".rstrip()


def elements_table(elements: list[EnvelopeElement]) -> list[dict]:
    """
    One row per element with its geometry and the channel budgets it offers.

    Budgets come straight from element.channels() so the table shows exactly the
    physical quantities the assembler will route — no parallel physics here.
    """
    rows: list[dict] = []
    for elem in elements:
        ch = elem.channels()
        cond: Budget | None = ch.get(Channel.CONDUCTION)
        store: Budget | None = ch.get(Channel.STORAGE)
        trans: Budget | None = ch.get(Channel.SOLAR_TRANSMISSION)
        opaque: Budget | None = ch.get(Channel.SOLAR_OPAQUE)

        area = getattr(elem, "area", None)
        row = {
            "Element": type(elem).__name__,
            "Area (m²)": "—" if not area else f"{area:.3g}",
            "Orientation": getattr(elem, "orientation", "—"),
            "Layers": _layers_str(elem.layers) if hasattr(elem, "layers") else "—",
            "U·A (W/K)": _fmt(cond.UA if cond else None, ""),
            "C (J/K)": _fmt(store.C if store else None, ""),
            "SHGC·A (m²)": _fmt(trans.shgcA if trans else None, ""),
            "α·A (m²)": _fmt(opaque.alphaA if opaque else None, ""),
            "Channels": ", ".join(sorted(c.name for c in ch)) or "—",
        }
        rows.append(row)
    return rows


# ── topology view (post-assembly RC ladder) ──────────────────────────────────
#
# Ladder layout (after the grey-box RC convention, e.g. Bacher & Madsen 2011):
#   - a top node rail carries the temperature STATES (T_room, plus T_wall etc.)
#   - a bottom ground rail; every capacitance and boundary source drops to it
#   - one labelled swimlane (dashed-separated column) per module
#
# Boundaries are bottom elements: T_ext is a voltage source to ground, G_sol a
# current (heat) source. This is electrically honest for a star topology while
# keeping the structured left-to-right reading of the reference diagram.

_COL_W = 3.6       # swimlane width
_TOP = 0.0         # node-rail height
_GND = -4.0        # ground-rail height


def _pname(mod, prefix: str) -> str:
    """First param of mod whose name starts with prefix (e.g. 'H' -> 'H_ve')."""
    for p in mod.params:
        if p.startswith(prefix):
            return p
    return ""


def _is_source(mod) -> bool:
    """
    True for a pure solar-gain injection (a heat source on T_room): owns solar
    but no conduction and no private mass. A heavy wall owns SOLAR_OPAQUE too,
    but folds it into its sol-air boundary, so it draws as a conductance branch.
    """
    return Channel.CONDUCTION not in mod.owns and not mod.private_states


_DROP = abs(_GND) - 0.6   # length of a vertical element from rail toward ground


def _drop_capacitor(d, e, x: float, label: str) -> None:
    """Capacitor from the node rail at column x down to the ground rail."""
    d += e.Capacitor().down().at((x, _TOP)).length(_DROP).label(label, fontsize=8, loc="bottom")
    d += e.Line().at((x, _GND + 0.6)).to((x, _GND))


def _draw_module_lane(d, e, mod, x0: float) -> None:
    """
    Draw one module inside its swimlane [x0, x0+_COL_W].

    Conductance modules put a resistor on the top rail from T_room's node toward
    a boundary source; heavy walls insert an intermediate mass node (with its own
    capacitor) on the rail. Solar modules are a current source on the bottom rail.
    """
    xmid = x0 + _COL_W / 2
    xend = x0 + _COL_W - 0.6   # boundary sits inside the lane, clear of the separator

    if _is_source(mod):
        # Heat source injected into T_room: current source from ground rail up.
        d += e.SourceI().up().at((xmid, _GND)).length(_DROP).label(mod.name, fontsize=8, loc="right")
        d += e.Line().at((xmid, _GND + _DROP)).to((xmid, _TOP))
        return

    if mod.private_states:
        # Heavy wall: rail goes T_room -R(H_in)- T_wall -R(H_out)- T_ext source.
        # T_wall sits at xmid with its capacitor dropping to ground.
        d += e.Resistor().at((x0, _TOP)).to((xmid, _TOP)).label(_pname(mod, "H_in"), fontsize=8, loc="bottom")
        d += e.Dot().at((xmid, _TOP)).label(mod.private_states[0], loc="top", fontsize=9)
        _drop_capacitor(d, e, xmid, _pname(mod, "C"))
        d += e.Resistor().at((xmid, _TOP)).to((xend, _TOP)).label(_pname(mod, "H_out"), fontsize=8, loc="bottom")
        _boundary_source(d, e, xend, "T_sol-air")
    else:
        # Direct loss: single resistor to a T_ext voltage source.
        d += e.Resistor().at((x0, _TOP)).to((xend, _TOP)).label(_pname(mod, "H"), fontsize=8)
        _boundary_source(d, e, xend, "T_ext")


def _boundary_source(d, e, x: float, label: str) -> None:
    """A boundary temperature as a voltage source from the node rail to ground."""
    d += e.SourceV().down().at((x, _TOP)).length(_DROP).label(label, fontsize=8, loc="right")
    d += e.Line().at((x, _GND + 0.6)).to((x, _GND))


def topology_svg(system: System) -> bytes:
    """
    Render the assembled star topology as an SVG string (RC ladder layout).

    A top node rail carries the temperature states (T_room at the left, plus any
    private mass nodes); a bottom ground rail collects every capacitor and
    boundary source. Each module occupies one labelled swimlane, left to right.
    """
    import schemdraw
    import schemdraw.elements as e

    branches = [m for m in system._modules if m.name != "RoomMass"]
    # Conductance/wall lanes first, source (solar) lanes last — reads left→right.
    branches.sort(key=_is_source)

    n = max(len(branches), 1)
    x_right = n * _COL_W - 0.6   # last boundary/source sits here

    d = schemdraw.Drawing(show=False)
    d.config(fontsize=10)

    # Rails.
    d += e.Line().at((0, _TOP)).to((x_right, _TOP))     # node rail
    d += e.Line().at((0, _GND)).to((x_right, _GND))     # ground rail
    d += e.Ground().at((0, _GND))

    # Room node + its capacity at the far left of the node rail.
    d += e.Dot(radius=0.1).at((0, _TOP)).label("T_room", loc="left", fontsize=11)
    _drop_capacitor(d, e, 0, "C_room")

    # Swimlanes.
    for i, mod in enumerate(branches):
        x0 = i * _COL_W
        if i > 0:
            d += e.Line().at((x0, _TOP)).to((x0, _GND)).linestyle(":").color("grey")
        _draw_module_lane(d, e, mod, x0)
        d += e.Label().at((x0 + _COL_W / 2, _TOP + 1.4)).label(mod.name, fontsize=10)

    return d.get_imagedata("png")
