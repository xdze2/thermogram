"""
Pydantic v2 models for the thermal library and FastAPI layer.

Naming convention for API schemas:
  *In  — request body (user → API)
  *Out — response body (API → user)

Core models (MaterialLayer, EnvelopeElement, Room) are plain Pydantic models
used throughout the computation layer as well as the API layer.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator, computed_field


# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------

class ElementType(str, Enum):
    wall   = "wall"
    window = "window"
    roof   = "roof"
    floor  = "floor"
    door   = "door"


class Orientation(str, Enum):
    N          = "N"
    NE         = "NE"
    E          = "E"
    SE         = "SE"
    S          = "S"
    SW         = "SW"
    W          = "W"
    NW         = "NW"
    HORIZONTAL = "horizontal"


# ---------------------------------------------------------------------------
# Core models (used by computation layer and API)
# ---------------------------------------------------------------------------

class MaterialLayer(BaseModel):
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


class EnvelopeElement(BaseModel):
    """A single opaque or glazed element of the building envelope."""

    name: str = Field(..., description="User-facing label.", examples=["South wall"])
    type: ElementType
    orientation: Orientation
    area_m2: float = Field(..., gt=0, description="Element area in m².")

    layers: list[MaterialLayer] = Field(
        default_factory=list,
        description="Material layers (inside → outside). Leave empty for windows.",
    )
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
    def check_layers_or_override(self) -> EnvelopeElement:
        if self.type != ElementType.window and not self.layers and self.u_value_override is None:
            raise ValueError("Opaque elements need either layers or u_value_override.")
        return self


class Room(BaseModel):
    """Full room / zone description."""

    name: str = Field(default="Room", description="User-facing room label.")
    floor_area_m2: float = Field(..., gt=0, description="Floor area in m².")
    height_m: float = Field(..., gt=0, description="Ceiling height in m.")

    latitude: float  = Field(..., ge=-90,  le=90,  description="Degrees north.")
    longitude: float = Field(..., ge=-180, le=180, description="Degrees east.")
    altitude_m: float = Field(default=0.0, description="Altitude above sea level in m.")

    elements: list[EnvelopeElement] = Field(
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

    @computed_field
    @property
    def volume(self) -> float:
        return self.floor_area_m2 * self.height_m


# ---------------------------------------------------------------------------
# Response schemas  (*Out)
# ---------------------------------------------------------------------------

class ContributionOut(BaseModel):
    """One additive term in a parameter's prior breakdown."""

    label: str   = Field(..., description="Element name and orientation tag.")
    value: float = Field(..., description="Contribution to the parameter (in parameter units).")
    sigma: float = Field(..., description="1-sigma uncertainty on this contribution.")
    detail: str  = Field(default="", description="Human-readable formula or source note.")


class ParameterPriorOut(BaseModel):
    """Gaussian prior for one RC model parameter, with per-element breakdown."""

    symbol: str      = Field(..., description="Short symbol used in equations.", examples=["H_env"])
    name: str        = Field(..., description="Full parameter name.")
    unit: str        = Field(..., description="Physical unit.", examples=["W/K", "MJ/K", "—"])
    description: str = Field(..., description="What this parameter controls in the RC model.")

    mu: float    = Field(..., description="Prior mean (best estimate from user description).")
    sigma: float = Field(..., description="Prior 1-sigma (quadrature sum over contributions).")

    contributions: list[ContributionOut] = Field(
        ..., description="Ordered additive breakdown: sum of values == mu."
    )


class RCModelOut(BaseModel):
    """2R2C + sol-air RC model with Gaussian priors on all five free parameters."""

    H_env:     ParameterPriorOut = Field(..., description="Opaque envelope conduction loss [W/K]. Drives sol-air path.")
    H_ve:      ParameterPriorOut = Field(..., description="Ventilation + window heat loss [W/K]. Direct T_ext→T_room.")
    C_wall:    ParameterPriorOut = Field(..., description="Envelope thermal mass [MJ/K].")
    C_room:    ParameterPriorOut = Field(..., description="Interior thermal mass [MJ/K].")
    alpha_eff: ParameterPriorOut = Field(..., description="Effective outer surface absorptivity [—].")
    H_int:     float             = Field(default=0.0, description="Inner-surface conductance [W/K], fixed from ISO 6946 (not fitted).")


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
