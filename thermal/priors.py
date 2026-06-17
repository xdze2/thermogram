"""
Construct RC model parameter priors from user-described envelope elements.

The 2R2C + sol-air model has five lumped parameters:
  H_env   [W/K]  — envelope conduction loss (= UA_envelope)
  H_ve    [W/K]  — ventilation heat loss
  C_wall  [J/K]  — thermal mass of heavy envelope layers
  C_room  [J/K]  — thermal mass of room interior (furniture, air, finishes)
  alpha   [-]    — effective solar absorptivity of opaque outer surfaces

For each parameter we compute:
  - mu    : best estimate from user inputs (ISO 6946 / material properties)
  - sigma : absolute uncertainty (1-sigma, same unit as mu)
  - contributions : list of (label, value, sigma) for each element's share

Uncertainties are based on:
  - H_env  : ±15% per element (thermal bridges, workmanship)
  - H_ve   : ±40% (ACH is a rough estimate)
  - C_wall : ±25% per element (effective penetration depth uncertainty)
  - C_room : ±60% (furnishing unknown)
  - alpha  : ±0.15 absolute (surface finish uncertainty)

All sigmas combine in quadrature across independent elements.
"""

import math
from dataclasses import dataclass

from .models import Room, EnvelopeElement, ElementType
from .iso6946 import element_u_value, layer_resistance, surface_resistances
from .materials_db import MATERIALS


# Relative uncertainty (1-sigma / mean) per parameter source
_REL_SIGMA_H_ENV = 0.15   # ISO 6946: ±15%
_REL_SIGMA_H_VE  = 0.40   # ACH estimate: ±40%
_REL_SIGMA_C_WALL = 0.25  # penetration depth: ±25%
_REL_SIGMA_C_ROOM = 0.60  # furnishing unknown: ±60%

# Solar absorptivity table by material key suffix / type
_ALPHA_TABLE: dict[str, tuple[float, float]] = {
    # (mean, sigma_abs)
    "brick_common":    (0.70, 0.10),
    "brick_hollow":    (0.65, 0.10),
    "concrete_dense":  (0.65, 0.10),
    "concrete_light":  (0.60, 0.10),
    "stone_limestone": (0.55, 0.10),
    "cement_plaster":  (0.60, 0.12),
    "lime_plaster":    (0.55, 0.12),
    "timber":          (0.60, 0.15),
    "wood_panel":      (0.60, 0.15),
    "bitumen_membrane":(0.90, 0.05),
    "clay_tile":       (0.80, 0.08),
    "metal_sheet":     (0.70, 0.15),
}
_ALPHA_DEFAULT = (0.65, 0.15)


def _outer_material_key(element: EnvelopeElement) -> str | None:
    """Return the key of the outermost layer (last in inside→outside list)."""
    if element.layers:
        return element.layers[-1].material_key
    return None


def _alpha_for_element(element: EnvelopeElement) -> tuple[float, float]:
    key = _outer_material_key(element)
    if key is None:
        return _ALPHA_DEFAULT
    for table_key, val in _ALPHA_TABLE.items():
        if table_key in key:
            return val
    return _ALPHA_DEFAULT


def _heavy_layer_mass(element: EnvelopeElement) -> float:
    """
    Effective thermal mass [J/K] of heavy layers only (rho > 500 kg/m³).
    Excludes insulation and plasterboard which store little heat.
    Multiplied by area to give volumetric total.
    """
    total = 0.0
    for layer in element.layers:
        mat = MATERIALS.get(layer.material_key)
        if mat is None:
            continue
        if mat.rho > 500:  # heavy material threshold
            total += mat.rho * mat.cp * layer.thickness * element.area
    return total


@dataclass
class Contribution:
    label: str         # e.g. "Wall S (brick 30cm)"
    value: float       # contribution to the parameter
    sigma: float       # 1-sigma uncertainty on this contribution
    detail: str = ""   # optional extra info shown to user


@dataclass
class ParameterPrior:
    name: str          # e.g. "H_env"
    symbol: str        # e.g. "H_env"
    unit: str
    description: str
    mu: float          # total best estimate
    sigma: float       # total 1-sigma (quadrature sum)
    contributions: list[Contribution]


def build_priors(room: Room) -> dict[str, ParameterPrior]:
    """
    Build all five parameter priors from a Room description.
    Returns dict keyed by parameter name.
    """
    h_env_contribs: list[Contribution] = []
    c_wall_contribs: list[Contribution] = []
    alpha_contribs: list[Contribution] = []   # area-weighted for alpha_eff

    total_opaque_area = 0.0
    alpha_area_sum = 0.0
    alpha_var_sum = 0.0

    for elem in room.elements:
        if elem.type == ElementType.WINDOW:
            # Windows contribute to H_env but not C_wall or alpha
            ua = element_u_value(elem) * elem.area
            sigma = ua * _REL_SIGMA_H_ENV
            h_env_contribs.append(Contribution(
                label=f"{elem.name}  [{elem.orientation.value}]",
                value=ua,
                sigma=sigma,
                detail=f"U={element_u_value(elem):.2f} W/m²K  ×  {elem.area} m²",
            ))
        else:
            # Opaque element
            ua = element_u_value(elem) * elem.area
            sigma_h = ua * _REL_SIGMA_H_ENV
            h_env_contribs.append(Contribution(
                label=f"{elem.name}  [{elem.orientation.value}]",
                value=ua,
                sigma=sigma_h,
                detail=f"U={element_u_value(elem):.2f} W/m²K  ×  {elem.area} m²",
            ))

            # Thermal mass of heavy layers
            c = _heavy_layer_mass(elem)
            if c > 0:
                sigma_c = c * _REL_SIGMA_C_WALL
                c_wall_contribs.append(Contribution(
                    label=f"{elem.name}  [{elem.orientation.value}]",
                    value=c,
                    sigma=sigma_c,
                    detail=f"{c/1e6:.2f} MJ/K from heavy layers",
                ))

            # Solar absorptivity (area-weighted mean)
            alpha_mu, alpha_sig = _alpha_for_element(elem)
            alpha_area_sum += alpha_mu * elem.area
            alpha_var_sum  += (alpha_sig * elem.area) ** 2
            total_opaque_area += elem.area

    # H_env
    h_env_mu    = sum(c.value for c in h_env_contribs)
    h_env_sigma = math.sqrt(sum(c.sigma**2 for c in h_env_contribs))

    # H_ve
    h_ve_mu    = 0.34 * room.ach * room.volume
    h_ve_sigma = h_ve_mu * _REL_SIGMA_H_VE

    # C_wall
    c_wall_mu    = sum(c.value for c in c_wall_contribs)
    c_wall_sigma = math.sqrt(sum(c.sigma**2 for c in c_wall_contribs)) if c_wall_contribs else 0.0

    # C_room (furniture + air + finishes — not described by user, weak prior)
    c_room_mu    = 20e3 * room.floor_area   # 20 kJ/(m²·K) × floor area [J/K]
    c_room_sigma = c_room_mu * _REL_SIGMA_C_ROOM

    # alpha_eff (area-weighted mean over opaque elements)
    if total_opaque_area > 0:
        alpha_mu    = alpha_area_sum / total_opaque_area
        alpha_sigma = math.sqrt(alpha_var_sum) / total_opaque_area
    else:
        alpha_mu, alpha_sigma = _ALPHA_DEFAULT

    alpha_contribs = []
    for elem in room.elements:
        if elem.type != ElementType.WINDOW:
            a_mu, a_sig = _alpha_for_element(elem)
            alpha_contribs.append(Contribution(
                label=f"{elem.name}  [{elem.orientation.value}]",
                value=a_mu,
                sigma=a_sig,
                detail=f"outer layer: {_outer_material_key(elem) or 'unknown'}  ×  {elem.area} m²",
            ))

    return {
        "H_env": ParameterPrior(
            name="Envelope heat loss",
            symbol="H_env",
            unit="W/K",
            description="Sum of U·A for all envelope elements. Drives steady-state heat loss.",
            mu=h_env_mu,
            sigma=h_env_sigma,
            contributions=h_env_contribs,
        ),
        "H_ve": ParameterPrior(
            name="Ventilation heat loss",
            symbol="H_ve",
            unit="W/K",
            description="ρ·cp·n·V from ACH and room volume. Wide prior: ACH is often uncertain.",
            mu=h_ve_mu,
            sigma=h_ve_sigma,
            contributions=[Contribution(
                label=f"Ventilation  (ACH={room.ach})",
                value=h_ve_mu,
                sigma=h_ve_sigma,
                detail=f"0.34 × {room.ach} ACH × {room.volume:.1f} m³",
            )],
        ),
        "C_wall": ParameterPrior(
            name="Envelope thermal mass",
            symbol="C_wall",
            unit="MJ/K",
            description="Heat stored in heavy envelope layers (brick, concrete…). Drives thermal lag.",
            mu=c_wall_mu,
            sigma=c_wall_sigma,
            contributions=c_wall_contribs,
        ),
        "C_room": ParameterPrior(
            name="Room interior thermal mass",
            symbol="C_room",
            unit="MJ/K",
            description="Furniture, floor finishes, partition walls. Not described by user — wide prior.",
            mu=c_room_mu,
            sigma=c_room_sigma,
            contributions=[Contribution(
                label=f"Interior estimate  ({room.floor_area} m² floor)",
                value=c_room_mu,
                sigma=c_room_sigma,
                detail=f"20 kJ/(m²·K) × {room.floor_area} m²  (weak prior)",
            )],
        ),
        "alpha_eff": ParameterPrior(
            name="Outer surface absorptivity",
            symbol="α_eff",
            unit="—",
            description="Area-weighted solar absorptivity of opaque outer surfaces. Drives sol-air temperature.",
            mu=alpha_mu,
            sigma=alpha_sigma,
            contributions=alpha_contribs,
        ),
    }
