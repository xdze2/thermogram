"""
Flux modules — the building blocks of the assembled RC system (physics_model.md §3).

Each module claims one or more `(element, channel)` cells and knows how to turn the
budgets it claims into parameter-prior contributions. This file implements only the
modules the current 2R2C topology needs:

  RoomMass    — the C_room base node (weak floor-area prior)
  DirectLoss  — Conductance@T_ext: window conduction + ventilation (→ H_ve)
  HeavyWall   — opaque envelope: U·A (→ H_env), C_heavy (→ C_wall), sol-air α (→ α_eff)
  SolarGain   — glazing-transmitted solar (SHGC budget; no current 5-param prior)

Every `derive_prior` returns plain `PriorTerm`s so the assembler can aggregate them
*exactly* as the legacy `build_priors` did (sum of means; quadrature of sigmas; the
area-weighted average for α). Matching that aggregation byte-for-byte is the Stage 2
success criterion.
"""

from __future__ import annotations

from dataclasses import dataclass

from .api_models import ContributionOut
from .channels import (
    Budget,
    Channel,
    CONDUCTION_EXT,
    SOLAR_SOLAIR,
    SOLAR_TRANSMITTED,
    STORAGE,
)
from .iso6946 import element_u_value


# Relative uncertainties (kept identical to legacy priors.py).
_REL_SIGMA_H_ENV = 0.15
_REL_SIGMA_H_VE = 0.40
_REL_SIGMA_C_WALL = 0.25
_REL_SIGMA_C_ROOM = 0.60

# Solar absorptivity table by material key substring (mean, sigma_abs).
_ALPHA_TABLE: dict[str, tuple[float, float]] = {
    "brick_common": (0.70, 0.10),
    "brick_hollow": (0.65, 0.10),
    "concrete_dense": (0.65, 0.10),
    "concrete_light": (0.60, 0.10),
    "stone_limestone": (0.55, 0.10),
    "cement_plaster": (0.60, 0.12),
    "lime_plaster": (0.55, 0.12),
    "timber": (0.60, 0.15),
    "wood_panel": (0.60, 0.15),
    "bitumen_membrane": (0.90, 0.05),
    "clay_tile": (0.80, 0.08),
    "metal_sheet": (0.70, 0.15),
}
_ALPHA_DEFAULT = (0.65, 0.15)


def _outer_material_key(element) -> str | None:
    if element.layers:
        return element.layers[-1].material_key
    return None


def alpha_for_element(element) -> tuple[float, float]:
    key = _outer_material_key(element)
    if key is None:
        return _ALPHA_DEFAULT
    for table_key, val in _ALPHA_TABLE.items():
        if table_key in key:
            return val
    return _ALPHA_DEFAULT


# ---------------------------------------------------------------------------
# Prior term — a module's contribution to one named parameter
# ---------------------------------------------------------------------------

@dataclass
class PriorTerm:
    """One additive contribution a module makes to a parameter prior.

    `aggregation` tells the assembler how to fold this term into the parameter:
      - "quadrature" : mu += value, var += sigma²            (H_env, H_ve, C_wall)
      - "area_weight": area-weighted mean of `value` (the α), area-weighted
                        quadrature of sigma; uses `weight` (= element area)
      - "scalar"     : a standalone parameter (C_room)
    """

    param: str
    value: float
    sigma: float
    contribution: ContributionOut
    aggregation: str = "quadrature"
    weight: float = 0.0


@dataclass
class FluxModule:
    """Base flux module. A module claims `(element, channel)` cells and derives priors."""

    def claims(self) -> list[tuple[object, Channel]]:
        """The (element, channel) cells this module owns."""
        raise NotImplementedError

    def derive_prior(self) -> list[PriorTerm]:
        raise NotImplementedError


def _ua_contribution(element) -> ContributionOut:
    u = element_u_value(element)
    ua = u * element.area_m2
    return ContributionOut(
        label=f"{element.name or element.uid}  [{element.orientation.value}]",
        value=ua,
        sigma=ua * _REL_SIGMA_H_ENV,
        detail=f"U={u:.2f} W/m²K  ×  {element.area_m2} m²",
    )


# ---------------------------------------------------------------------------
# RoomMass — the base node
# ---------------------------------------------------------------------------

@dataclass
class RoomMass(FluxModule):
    floor_area_m2: float

    def claims(self) -> list[tuple[object, Channel]]:
        return []  # owns no element channel — it is the room balance itself

    def derive_prior(self) -> list[PriorTerm]:
        mu = 20e3 * self.floor_area_m2
        sigma = mu * _REL_SIGMA_C_ROOM
        contrib = ContributionOut(
            label=f"Interior estimate  ({self.floor_area_m2} m² floor)",
            value=mu,
            sigma=sigma,
            detail=f"20 kJ/(m²·K) × {self.floor_area_m2} m²  (weak prior)",
        )
        return [PriorTerm("C_room", mu, sigma, contrib, aggregation="scalar")]


# ---------------------------------------------------------------------------
# DirectLoss — Conductance@T_ext (windows + ventilation), → H_ve
# ---------------------------------------------------------------------------

@dataclass
class Ventilation(FluxModule):
    """The ventilation half of DirectLoss: 0.34·ACH·V into H_ve."""

    ach: float
    volume: float

    def claims(self) -> list[tuple[object, Channel]]:
        return []  # ventilation is a room property, not an element channel

    def derive_prior(self) -> list[PriorTerm]:
        mu = 0.34 * self.ach * self.volume
        sigma = mu * _REL_SIGMA_H_VE
        contrib = ContributionOut(
            label=f"Ventilation  (ACH={self.ach})",
            value=mu,
            sigma=sigma,
            detail=f"0.34 × {self.ach} ACH × {self.volume:.1f} m³",
        )
        return [PriorTerm("H_ve", mu, sigma, contrib)]


@dataclass
class WindowLoss(FluxModule):
    """A window's conduction (CONDUCTION@T_ext), routed to H_ve."""

    element: object

    def claims(self) -> list[tuple[object, Channel]]:
        # Window also offers SOLAR_TRANSMITTED, owned by SolarGain.
        return [(self.element, CONDUCTION_EXT)]

    def derive_prior(self) -> list[PriorTerm]:
        c = _ua_contribution(self.element)
        return [PriorTerm("H_ve", c.value, c.sigma, c)]


# ---------------------------------------------------------------------------
# HeavyWall — opaque envelope element (H_env + C_wall + α_eff)
# ---------------------------------------------------------------------------

@dataclass
class HeavyWall(FluxModule):
    """An opaque element: conduction (→H_env), heavy mass (→C_wall), sol-air (→α_eff).

    Claims CONDUCTION@T_ext, SOLAR@sol-air, and STORAGE (when heavy) for one element.
    A light opaque element still uses this module — it simply offers no STORAGE.
    """

    element: object
    budgets: dict[Channel, Budget]

    def claims(self) -> list[tuple[object, Channel]]:
        cells = [(self.element, CONDUCTION_EXT), (self.element, SOLAR_SOLAIR)]
        if STORAGE in self.budgets:
            cells.append((self.element, STORAGE))
        return cells

    def derive_prior(self) -> list[PriorTerm]:
        terms: list[PriorTerm] = []

        # H_env from CONDUCTION@T_ext
        c = _ua_contribution(self.element)
        terms.append(PriorTerm("H_env", c.value, c.sigma, c))

        # C_wall from STORAGE (heavy layers only; absent for light elements)
        if STORAGE in self.budgets:
            cw = self.budgets[STORAGE].value
            sigma_c = cw * _REL_SIGMA_C_WALL
            terms.append(PriorTerm(
                "C_wall", cw, sigma_c,
                ContributionOut(
                    label=f"{self.element.name or self.element.uid}  [{self.element.orientation.value}]",
                    value=cw,
                    sigma=sigma_c,
                    detail=f"{cw/1e6:.2f} MJ/K from heavy layers",
                ),
            ))

        # α_eff from SOLAR@sol-air (area-weighted)
        a_mu, a_sig = alpha_for_element(self.element)
        area = self.element.area_m2
        terms.append(PriorTerm(
            "alpha_eff", a_mu, a_sig,
            ContributionOut(
                label=f"{self.element.name or self.element.uid}  [{self.element.orientation.value}]",
                value=a_mu,
                sigma=a_sig,
                detail=f"outer layer: {_outer_material_key(self.element) or 'unknown'}  ×  {area} m²",
            ),
            aggregation="area_weight",
            weight=area,
        ))

        return terms


# ---------------------------------------------------------------------------
# SolarGain — glazing-transmitted solar (no current 5-parameter prior)
# ---------------------------------------------------------------------------

@dataclass
class SolarGain(FluxModule):
    """Glazing-transmitted gain. Claims SOLAR@transmitted; contributes no 2R2C prior."""

    element: object

    def claims(self) -> list[tuple[object, Channel]]:
        return [(self.element, SOLAR_TRANSMITTED)]

    def derive_prior(self) -> list[PriorTerm]:
        return []
