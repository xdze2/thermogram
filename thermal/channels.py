"""
Channels — the conserved per-element budgets the modular engine routes to modules.

This file holds the glossary of the modular RC vocabulary. Keep these distinct:

  Element    declarative geometry + materials of one surface (api_models.py). Offers
             budgets; owns no physics.
  Mechanism  a kind of heat path: CONDUCTION | SOLAR | STORAGE.
  Source     the *other end* of a branch — a boundary temperature (T_ext / T_ground /
             T_adj), a solar driver (G_solair / G_transmitted), or `—` for storage
             (a capacitance has no other end). A source that carries a measured
             timeseries is a *signal*; not every source is a signal (storage isn't).
  Channel    = (Mechanism, Source). A *budget slot* an element offers — e.g. a wall
             has U·A worth of CONDUCTION@T_ext available to be claimed. A channel is
             ACCOUNTING, not yet a branch: it is the unit at which the assembler
             enforces exactly-one-owner, so a budget can't be silently spent twice.
  Module     (modules.py) claims channels (accounting) and emits RC branches (physics).
             "module + source = one branch" in the assembled circuit.

This file owns only the *budget computation* (the conserved quantities, model-agnostic,
computed once from geometry + ISO 6946 + layers). Turning a budget into a prior lives in
the modules; routing channels to modules lives in the assembler.

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
    """A kind of heat path an element can offer."""

    CONDUCTION = "CONDUCTION"  # U·A through the element to a boundary
    SOLAR = "SOLAR"            # absorbed/transmitted shortwave gain
    STORAGE = "STORAGE"        # heat capacity of heavy layers (a node, not a flux)


class Source(str, Enum):
    """The other end of a branch: a boundary temp, a solar driver, or `—` for storage.

    The temperature/irradiance sources double as *signals* (driving timeseries) at
    simulation time; STORAGE's `NONE` is the exception — a capacitance has no other end.
    """

    T_EXT = "T_ext"
    T_GROUND = "T_ground"
    T_ADJ = "T_adj"
    G_SOLAIR = "G_sol_solair"          # opaque exterior sol-air drive
    G_TRANSMITTED = "G_sol_transmitted"  # glazing-transmitted gain
    NONE = "—"                          # STORAGE: a capacity, no source/flux


@dataclass(frozen=True)
class Channel:
    """A `(mechanism, source)` budget slot — the unit of exactly-once ownership.

    Accounting, not physics: a channel says "this element offers this much of this heat
    path to this boundary, claimable by one module." The RC branch itself is emitted
    later by the owning module's `dynamics()`.
    """

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
