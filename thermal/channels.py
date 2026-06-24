"""
Channels — the conserved per-element budgets the modular engine routes to modules.

A *channel* is a `(mechanism, source)` key (physics_model.md §2): a conserved budget an
element offers, computed once from geometry + ISO 6946 + layers, model-agnostic. The
unit of ownership is the `(element, channel)` pair; the assembler routes each to exactly
one module.

This module owns only the *budget computation* (the conserved quantities). How a budget
becomes a parameter prior lives in the modules (`thermal/modules.py`); how channels are
routed to modules lives in the assembler (`thermal/assembler.py`).

Scope note: only the channels the current 2R2C topology needs are produced here
(CONDUCTION@T_ext, SOLAR sol-air / transmitted, STORAGE). Ground/adjacent sources are
deferred with their physics (see the roadmap).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .iso6946 import element_u_value
from .materials_db import MATERIALS


class Mechanism(str, Enum):
    CONDUCTION = "CONDUCTION"
    SOLAR = "SOLAR"
    STORAGE = "STORAGE"


class Source(str, Enum):
    T_EXT = "T_ext"
    T_GROUND = "T_ground"
    T_ADJ = "T_adj"
    G_SOLAIR = "G_sol_solair"          # opaque exterior sol-air drive
    G_TRANSMITTED = "G_sol_transmitted"  # glazing-transmitted gain
    NONE = "—"                          # STORAGE: capacity, not a flux


@dataclass(frozen=True)
class Channel:
    """The `(mechanism, source)` ownership key."""

    mechanism: Mechanism
    source: Source

    def __str__(self) -> str:
        return f"{self.mechanism.value}@{self.source.value}"


# Canonical channels of the current topology.
CONDUCTION_EXT = Channel(Mechanism.CONDUCTION, Source.T_EXT)
SOLAR_SOLAIR = Channel(Mechanism.SOLAR, Source.G_SOLAIR)
SOLAR_TRANSMITTED = Channel(Mechanism.SOLAR, Source.G_TRANSMITTED)
STORAGE = Channel(Mechanism.STORAGE, Source.NONE)


@dataclass(frozen=True)
class Budget:
    """A conserved quantity an element offers on one channel.

    `value` is the channel's primary conserved quantity in SI:
      - CONDUCTION : U·A           [W/K]
      - SOLAR      : aperture area  [m²] (the α / SHGC weight is the module's param)
      - STORAGE    : C_heavy        [J/K]
    """

    value: float


# --- heavy-layer thermal mass (ρ>500 layers), used by the STORAGE budget ------
# Kept identical to priors._heavy_layer_mass so the C_wall prior is byte-preserved.

HEAVY_RHO_THRESHOLD = 500.0  # kg/m³


def heavy_layer_mass(element) -> float:
    """Effective thermal mass [J/K] of heavy layers only (ρ > 500 kg/m³)."""
    total = 0.0
    for layer in element.layers:
        mat = MATERIALS.get(layer.material_key)
        if mat is None:
            continue
        if mat.rho > HEAVY_RHO_THRESHOLD:
            total += mat.rho * mat.cp * layer.thickness_m * element.area_m2
    return total


def element_channels(element) -> dict[Channel, Budget]:
    """The conserved budgets one element offers, keyed by channel.

    Current-topology routing:
      - every element conducts to T_ext  → CONDUCTION@T_ext (U·A)
      - opaque elements drive the sol-air path → SOLAR@sol-air (area), and offer
        STORAGE when they have heavy layers (C_heavy > 0)
      - windows transmit solar → SOLAR@transmitted (area)
    """
    ua = element_u_value(element) * element.area_m2
    out: dict[Channel, Budget] = {CONDUCTION_EXT: Budget(ua)}

    if element.is_opaque:
        out[SOLAR_SOLAIR] = Budget(element.area_m2)
        c_heavy = heavy_layer_mass(element)
        if c_heavy > 0:
            out[STORAGE] = Budget(c_heavy)
    else:
        out[SOLAR_TRANSMITTED] = Budget(element.area_m2)

    return out
