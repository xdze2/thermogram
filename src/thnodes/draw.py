"""
Rendering layer: turn an assembled system into a topology view.

  - topology_svg(system) -> bytes (SVG)   post-assembly RC star schematic (schemdraw)

Physics is never recomputed here: the schematic reads the assembled System's modules.
"""

from __future__ import annotations

from .channels import Channel
from .assembler import System


# ── topology view (post-assembly RC star) ────────────────────────────────────
#
# Star layout: every module connects the SINGLE room node to a boundary, so the
# whole top rail is one equipotential node — T_room. Each module hangs as its own
# vertical branch dropping from that rail to the common ground rail at the bottom:
#
#   T_room  ●━━━━━━━━━━━●━━━━━━●         (one node — the top rail)
#           │           │      │
#          ─┴─C_room   [R]    ( )↑ source
#           │           │      │
#          GND ━━━━━━━━━┷━━━━━━┷         (common ground rail)
#
# Boundaries live at the bottom of each branch: a T_ext / sol-air voltage source,
# or — for pure solar gain — a current (heat) source injected straight into T_room.

_COL_W = 2.4       # horizontal spacing between branches
_TOP = 0.0         # T_room node-rail height
_GND = -7.0        # ground-rail height (tall enough for the R–node–R–V stack)


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


# Labels are placed explicitly at known coordinates (schemdraw's element-relative
# label placement on rotated elements is unreliable). Component names sit on the
# LEFT of a branch, node/boundary names on the RIGHT, so they never collide.
_R_LEN = 1.8       # length of a series resistor
_LBL_DX = 0.45     # horizontal offset of a label from its branch


def _name_left(d, e, x: float, y: float, text: str) -> None:
    d += e.Label().at((x - _LBL_DX, y)).label(text, fontsize=8, halign="right")


def _name_right(d, e, x: float, y: float, text: str) -> None:
    d += e.Label().at((x + _LBL_DX, y)).label(text, fontsize=8, halign="left")


def _draw_branch(d, e, mod, x: float) -> None:
    """Draw one module as a vertical branch hanging from the T_room rail at x."""
    d += e.Dot(radius=0.06).at((x, _TOP))

    if _is_source(mod):
        # Pure solar gain: a heat-current source pushing up into T_room.
        # (The branch is already named by the column header, so no extra label.)
        d += e.SourceI().up().at((x, _GND)).toy(_TOP)
        return

    if mod.private_states:
        # Heavy wall: R(H_in) — T_wall node (C to ground) — R(H_out) — sol-air source.
        y_node = _TOP - _R_LEN
        y_r2 = y_node - _R_LEN
        d += e.Resistor().down().at((x, _TOP)).toy(y_node)
        _name_left(d, e, x, _TOP - _R_LEN / 2, _pname(mod, "H_in"))
        d += (node := e.Dot().at((x, y_node)))
        _name_right(d, e, x, y_node, mod.private_states[0])
        # C_wall taps off the T_wall node, sideways then down to the ground rail.
        d += e.Line().right().at(node.center).length(1.0)
        d += e.Capacitor().down().toy(_GND + 0.7)
        _name_right(d, e, x + 1.0, (y_node + _GND) / 2, _pname(mod, "C"))
        d += e.Line().down().toy(_GND)
        # H_out resistor continues down to the sol-air source.
        d += e.Resistor().down().at((x, y_node)).toy(y_r2)
        _name_left(d, e, x, (y_node + y_r2) / 2, _pname(mod, "H_out"))
        d += e.SourceV().down().at((x, y_r2)).toy(_GND + 0.7)
        _name_right(d, e, x, (y_r2 + _GND) / 2, "T_sol-air")
        d += e.Line().down().toy(_GND)
    else:
        # Direct loss: single resistor down to a T_ext voltage source.
        y_r = _TOP - _R_LEN
        d += e.Resistor().down().at((x, _TOP)).toy(y_r)
        _name_left(d, e, x, _TOP - _R_LEN / 2, _pname(mod, "H"))
        d += e.SourceV().down().at((x, y_r)).toy(_GND + 0.7)
        _name_right(d, e, x, (y_r + _GND) / 2, "T_ext")
        d += e.Line().down().toy(_GND)


def topology_svg(system: System) -> bytes:
    """
    Render the assembled star topology as an SVG (vertical-branch star layout).

    Returns SVG bytes (UTF-8 encoded XML).

    The top rail is the single T_room node; every module hangs from it as a
    vertical branch down to the common ground rail. C_room drops from the rail at
    the left; conductances become R→boundary-source branches (heavy walls insert a
    T_wall mass node with its own C); pure solar gain is a current source into the
    rail. Module names label each branch along the top.
    """
    import schemdraw
    import schemdraw.elements as e

    branches = [m for m in system._modules if m.name != "RoomMass"]
    # Conductance/wall branches first, source (solar) branches last — reads left→right.
    branches.sort(key=_is_source)

    # x=0 is C_room; branches start one column to its right.
    n = len(branches)
    x_right = (n + 1) * _COL_W

    d = schemdraw.Drawing(show=False)
    d.config(fontsize=10)

    # The two rails.
    d += e.Line().at((0, _TOP)).to((x_right - _COL_W, _TOP))   # T_room node rail
    d += e.Line().at((0, _GND)).to((x_right - _COL_W, _GND))   # ground rail
    d += e.Ground().at((0, _GND))

    # T_room node + C_room at the far left.
    d += e.Dot(radius=0.1).at((0, _TOP)).label("T_room", loc="left", fontsize=11)
    d += e.Capacitor().down().at((0, _TOP)).toy(_GND + 0.7)
    _name_right(d, e, 0, (_TOP + _GND) / 2, "C_room")
    d += e.Line().down().toy(_GND)

    # One vertical branch per module.
    for i, mod in enumerate(branches):
        x = (i + 1) * _COL_W
        d += e.Label().at((x, _TOP + 0.7)).label(mod.name, fontsize=9)
        _draw_branch(d, e, mod, x)

    return d.get_imagedata("svg")
