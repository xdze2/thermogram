"""
Pydantic v2 schemas for the FastAPI layer.

Naming convention:
  *In  — request body (user → API)
  *Out — response body (API → user)

The central concept is RCModelOut: a 2R2C + sol-air model where each of the
five parameters carries a Gaussian prior derived from the room description.
A "simulation" is a forward run at theta = prior means; a "fit" updates those
means and sigmas from observed data.  Same model, different theta source.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Shared enums (mirror thermal/models.py but decoupled for the API layer)
# ---------------------------------------------------------------------------

class ElementTypeEnum(str, Enum):
    wall   = "wall"
    window = "window"
    roof   = "roof"
    floor  = "floor"
    door   = "door"


class OrientationEnum(str, Enum):
    N          = "N"
    NE         = "NE"
    E          = "E"
    SE         = "SE"
    S          = "S"
    SW         = "SW"
    W          = "W"
    NW         = "NW"
    horizontal = "horizontal"


# ---------------------------------------------------------------------------
# Request schemas  (*In)
# ---------------------------------------------------------------------------

class MaterialLayerIn(BaseModel):
    """One layer in a wall/roof/floor cross-section, inside → outside order."""

    material_key: str = Field(
        ...,
        description="Key from the materials database (see GET /api/materials).",
        examples=["brick_common", "mineral_wool"],
    )
    thickness_m: float = Field(
        ...,
        gt=0,
        description="Layer thickness in metres.",
        examples=[0.30, 0.14],
    )


class EnvelopeElementIn(BaseModel):
    """A single opaque or glazed element of the building envelope."""

    name: str = Field(..., description="User-facing label.", examples=["South wall"])
    type: ElementTypeEnum
    orientation: OrientationEnum
    area_m2: float = Field(..., gt=0, description="Element area in m².")

    # Opaque elements: define via layer stack
    layers: list[MaterialLayerIn] = Field(
        default_factory=list,
        description="Material layers (inside → outside). Leave empty for windows.",
    )

    # Windows / doors: direct U-value
    u_value_override: float | None = Field(
        default=None,
        gt=0,
        description="Fixed U-value [W/(m²·K)]. If set, layers are ignored.",
        examples=[1.4],
    )
    shgc: float = Field(
        default=0.6,
        ge=0,
        le=1,
        description="Solar heat gain coefficient (windows only).",
    )
    is_ground_contact: bool = Field(
        default=False,
        description="True for slab-on-grade floors or basement walls.",
    )
    tilt_deg: float = Field(
        default=90.0,
        ge=0,
        le=180,
        description="Tilt from horizontal in degrees. 0=horizontal roof, 90=vertical wall.",
    )

    @model_validator(mode="after")
    def check_layers_or_override(self) -> EnvelopeElementIn:
        if self.type != ElementTypeEnum.window and not self.layers and self.u_value_override is None:
            raise ValueError("Opaque elements need either layers or u_value_override.")
        return self


class RoomIn(BaseModel):
    """
    Complete single-zone room description.
    Used by POST /api/room/rc_model (priors) and POST /api/room/fit.
    """

    name: str = Field(default="Room", description="User-facing room label.")
    floor_area_m2: float = Field(..., gt=0, description="Floor area in m².")
    height_m: float = Field(..., gt=0, description="Ceiling height in m.")

    latitude: float  = Field(..., ge=-90,  le=90,  description="Degrees north.")
    longitude: float = Field(..., ge=-180, le=180, description="Degrees east.")
    altitude_m: float = Field(default=0.0, description="Altitude above sea level in m.")

    elements: list[EnvelopeElementIn] = Field(
        ..., min_length=1, description="Envelope elements (walls, windows, roof, floor)."
    )

    internal_gains_w: float = Field(
        default=0.0, ge=0,
        description="Constant internal heat gains (people + equipment + lighting) in W.",
    )
    ach: float = Field(
        default=0.5, gt=0,
        description="Air changes per hour for infiltration/ventilation.",
    )


# ---------------------------------------------------------------------------
# Response schemas  (*Out)
# ---------------------------------------------------------------------------

class ContributionOut(BaseModel):
    """
    One additive term in a parameter's prior breakdown.

    Example rendering:
      + 13.4 W/K  ±2.0  │████████░░│  South wall [S]   U=1.34 W/m²K × 10 m²
    """

    label: str = Field(..., description="Element name and orientation tag.")
    value: float = Field(..., description="Contribution to the parameter (in parameter units).")
    sigma: float = Field(..., description="1-sigma uncertainty on this contribution.")
    detail: str  = Field(default="", description="Human-readable formula or source note.")


class ParameterPriorOut(BaseModel):
    """
    Gaussian prior for one RC model parameter, with per-element breakdown.

    The prior is log-normal in practice (positivity constraint) but we
    report mu/sigma in linear units for readability.  For fitting, convert:
      mu_log    = log(mu)
      sigma_log = sigma / mu   (coefficient of variation)
    """

    symbol: str  = Field(..., description="Short symbol used in equations.", examples=["H_env"])
    name: str    = Field(..., description="Full parameter name.")
    unit: str    = Field(..., description="Physical unit.", examples=["W/K", "MJ/K", "—"])
    description: str = Field(..., description="What this parameter controls in the RC model.")

    mu: float    = Field(..., description="Prior mean (best estimate from user description).")
    sigma: float = Field(..., description="Prior 1-sigma (quadrature sum over contributions).")

    @property
    def cv_pct(self) -> float:
        """Coefficient of variation as a percentage."""
        return self.sigma / self.mu * 100 if self.mu > 0 else 0.0

    contributions: list[ContributionOut] = Field(
        ..., description="Ordered additive breakdown: sum of values == mu."
    )


class RCModelOut(BaseModel):
    """
    2R2C + sol-air RC model with Gaussian priors on all five parameters.

    Topology (per heavy opaque element):
      T_sa(t) ──R_ext──[C_wall]──R_int──[C_room]
                                            │
                                      Q_internal + Q_sol_window
                                      R_ve ── T_out

    where T_sa = T_out + alpha_eff · I_incident / h_ext  (sol-air temperature).

    A forward simulation uses theta = (mu_H_env, mu_H_ve, mu_C_wall,
    mu_C_room, mu_alpha_eff).  A Bayesian fit updates these from data.
    """

    H_env:     ParameterPriorOut = Field(..., description="Envelope conduction loss [W/K].")
    H_ve:      ParameterPriorOut = Field(..., description="Ventilation heat loss [W/K].")
    C_wall:    ParameterPriorOut = Field(..., description="Envelope thermal mass [MJ/K].")
    C_room:    ParameterPriorOut = Field(..., description="Interior thermal mass [MJ/K].")
    alpha_eff: ParameterPriorOut = Field(..., description="Effective outer surface absorptivity [—].")


# ---------------------------------------------------------------------------
# Materials endpoint
# ---------------------------------------------------------------------------

class MaterialOut(BaseModel):
    key: str
    name: str
    lambda_W_mK: float = Field(..., description="Thermal conductivity [W/(m·K)].")
    rho_kg_m3: float   = Field(..., description="Density [kg/m³].")
    cp_J_kgK: float    = Field(..., description="Specific heat capacity [J/(kg·K)].")
    is_heavy: bool     = Field(..., description="True if rho > 500 kg/m³ (contributes to C_wall).")
