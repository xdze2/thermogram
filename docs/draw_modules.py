#!/usr/bin/env python3
"""
Generate generic illustrative RC schematics for each module form.

Standalone — not part of the app (the engine-driven, per-study renderer is
Stage 4's `thermal/draw.py`). This just draws the four canonical *forms* from
`physics_model.md` as reusable glyphs for the docs.

Run (schemdraw is not a project dependency, pull it transiently):

    uv run --with schemdraw docs/draw_modules.py

Outputs PNG (and SVG) into docs/diagrams/.

RC ↔ thermal analogy used throughout:
    voltage  ↔ temperature T        [K]
    current  ↔ heat flux Q          [W]
    resistor ↔ thermal resistance   R = 1/H   [K/W]
    capacitor↔ thermal mass         C          [J/K]
    ground   ↔ datum (0 K reference)
    V source ↔ prescribed temperature (T_ext, T_ground, T_adj)
    I source ↔ prescribed heat flux (solar gain, HVAC)
"""

from __future__ import annotations

from pathlib import Path

import schemdraw
import schemdraw.elements as elm

# matplotlib backend renders both PNG and SVG; the default svg backend is SVG-only
schemdraw.use("matplotlib")

OUT = Path(__file__).parent / "diagrams"
OUT.mkdir(exist_ok=True)


def save(d: schemdraw.Drawing, name: str) -> None:
    """Write both PNG (for embedding) and SVG (crisp/themeable)."""
    for ext in ("png", "svg"):
        d.save(str(OUT / f"{name}.{ext}"), dpi=150)
    print(f"  wrote diagrams/{name}.png + .svg")


def room_node(d: schemdraw.Drawing, label: str = "$T_{room}$"):
    """Draw the room node as a dot with a capacitor to ground; return the top dot."""
    top = d.add(elm.Dot().label(label, "right"))
    d.add(elm.Capacitor().down().label("$C_{room}$", "left"))
    d.add(elm.Ground())
    return top


# ---------------------------------------------------------------------------
# 1. RoomMass — the base node: capacity to the datum, every flux writes here
# ---------------------------------------------------------------------------

def note(d: schemdraw.Drawing, text: str, x: float, y: float, color: str = "navy") -> None:
    """Absolute-positioned caption — robust across schemdraw versions."""
    d.add(elm.Label().at((x, y)).label(text, "center", fontsize=11, color=color))


def draw_room_mass() -> None:
    with schemdraw.Drawing(show=False) as d:
        d.config(unit=2.4, fontsize=13)
        d += elm.Dot().label("$T_{room}$", "right")
        d += elm.Capacitor().down().label("$C_{room}$", "right")
        d += elm.Ground()
        note(d, "$C_{room}\\,\\dot T_{room} = \\sum Q_i$", -1.0, 1.2)
        save(d, "module_room_mass")


# ---------------------------------------------------------------------------
# 2. Conductance — T_src --R(=1/U)--> T_room  (DirectLoss/GroundLoss/AdjacentLoss)
# ---------------------------------------------------------------------------

def draw_conductance() -> None:
    with schemdraw.Drawing(show=False) as d:
        d.config(unit=2.4, fontsize=13)
        src = d.add(elm.SourceV().up().label("$T_{src}$\n($T_{ext}$ / $T_{gnd}$ / $T_{adj}$)", "left"))
        d.add(elm.Line().right().length(1))
        d.add(elm.Resistor().right().label("$R = 1/H$"))
        room = d.add(elm.Dot().label("$T_{room}$", "right"))
        d.add(elm.Capacitor().down().length(2.4).label("$C_{room}$", "right"))
        gnd = d.add(elm.Ground())
        # close source bottom to ground
        d.add(elm.Line().down().toy(gnd.center).at(src.start))
        d.add(elm.Line().right().tox(room.center))
        note(d, "$Q = H\\,(T_{src} - T_{room})$", 2.4, 1.4)
        save(d, "module_conductance")


# ---------------------------------------------------------------------------
# 3. SolarGain — current source injected into T_room  (alpha * Q_src)
# ---------------------------------------------------------------------------

def draw_solar_gain() -> None:
    with schemdraw.Drawing(show=False) as d:
        d.config(unit=2.4, fontsize=13)
        room = d.add(elm.Dot().label("$T_{room}$ (or mass node)", "right"))
        d.add(elm.Capacitor().down().label("$C$", "left"))
        gnd = d.add(elm.Ground())
        # current source pushing flux into the node from the datum
        d.add(elm.Line().left().at(room.center).length(2))
        src = d.add(elm.SourceI().down().reverse().label("$\\alpha\\,Q_{src}$", "left"))
        d.add(elm.Line().right().tox(gnd.center).toy(gnd.center))
        note(d, "$Q = \\alpha \\cdot Q_{src}$\n(SHGC·G  /  HVAC effic.)", -3.4, 1.2)
        save(d, "module_solar_gain")


# ---------------------------------------------------------------------------
# 4. RChain (DelayedConductance) — N-node mass between T_src and T_room
# ---------------------------------------------------------------------------

def draw_rchain(n: int = 3, name: str = "module_rchain") -> None:
    with schemdraw.Drawing(show=False) as d:
        d.config(unit=1.7, fontsize=12)
        src = d.add(elm.SourceV().up().label("$T_{src}$", "left"))
        d.add(elm.Line().right().length(0.8))
        d.add(elm.Resistor().right().label("$H_{out}$", "bottom"))

        for i in range(1, n + 1):
            d.add(elm.Dot().label(f"$T_{{m{i}}}$", "top", ofst=0.3))
            # capacitor down to datum; push label down its body, clear of the node label
            d.push()
            d.add(elm.Capacitor().down().length(1.8).label(f"$C_{i}$", "right", ofst=(0, 0.9)))
            d.add(elm.Ground())
            d.pop()
            if i < n:
                d.add(elm.Resistor().right().label(f"$H_{i}$", "bottom"))

        d.add(elm.Resistor().right().label("$H_{in}$", "bottom"))
        room = d.add(elm.Dot().label("$T_{room}$", "right", ofst=0.15))
        d.add(elm.Capacitor().down().length(1.8).label("$C_{room}$", "right", ofst=(0, 0.9)))
        gnd = d.add(elm.Ground())
        # source return wire along the bottom datum
        d.add(elm.Line().down().toy(gnd.center).at(src.start))

        note(d, "N-cell wall: $R_i = R_{tot}/N$,  $C_i = C_{tot}/N$\n"
                "(sliced in layer order — captures ITE vs ITI)", n * 1.5, 3.3)
        save(d, name)


def draw_rchain_variants() -> None:
    # N=1: the classic 2R2C heavy wall
    with schemdraw.Drawing(show=False) as d:
        d.config(unit=2.0, fontsize=12)
        src = d.add(elm.SourceV().up().label("$T_{src}$", "left"))
        d.add(elm.Line().right().length(0.6))
        d.add(elm.Resistor().right().label("$H_{out}$", "bottom"))
        d.add(elm.Dot().label("$T_{wall}$", "top", ofst=0.15))
        d.push()
        d.add(elm.Capacitor().down().length(1.8).label("$C_{wall}$", "left"))
        d.add(elm.Ground())
        d.pop()
        d.add(elm.Resistor().right().label("$H_{in}$", "bottom"))
        d.add(elm.Dot().label("$T_{room}$", "top", ofst=0.15))
        d.add(elm.Capacitor().down().length(1.8).label("$C_{room}$", "right"))
        gnd = d.add(elm.Ground())
        d.add(elm.Line().down().toy(gnd.center).at(src.start))
        note(d, "N=1: classic 2R2C heavy wall", 3, 3.0)
        save(d, "module_rchain_n1")

    # N=1, H_out = 0: one-sided internal mass (furniture)
    with schemdraw.Drawing(show=False) as d:
        d.config(unit=2.0, fontsize=12)
        d.add(elm.Dot().label("$T_{m}$", "top", ofst=0.15))
        d.push()
        d.add(elm.Capacitor().down().length(1.8).label("$C_m$", "left"))
        d.add(elm.Ground())
        d.pop()
        d.add(elm.Resistor().right().label("$H_{in}=1/R_m$", "bottom"))
        d.add(elm.Dot().label("$T_{room}$", "top", ofst=0.15))
        d.add(elm.Capacitor().down().length(1.8).label("$C_{room}$", "right"))
        d.add(elm.Ground())
        note(d, "$H_{out}=0$: one-sided internal mass (furniture)", 1.5, 3.0)
        save(d, "module_rchain_furniture")


if __name__ == "__main__":
    print(f"schemdraw {schemdraw.__version__} → {OUT}/")
    draw_room_mass()
    draw_conductance()
    draw_solar_gain()
    draw_rchain(n=3)
    draw_rchain_variants()
    print("done.")
