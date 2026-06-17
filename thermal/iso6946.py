"""
U-value and thermal resistance calculations per ISO 6946:2017.
"""

from .materials_db import MATERIALS
from .api_models import EnvelopeElement, ElementType, Orientation, MaterialLayer


def surface_resistances(element: EnvelopeElement) -> tuple[float, float]:
    """Return (Rsi, Rso) in m²·K/W based on element type and heat flow direction."""
    if element.type in (ElementType.wall, ElementType.window, ElementType.door):
        return 0.13, 0.04
    elif element.type == ElementType.roof:
        return 0.10, 0.04
    elif element.type == ElementType.floor:
        if element.is_ground_contact:
            return 0.17, 0.00  # ground contact: no Rso (ISO 13370)
        return 0.17, 0.04
    raise ValueError(f"Unhandled element type: {element.type!r}")


def layer_resistance(layer: MaterialLayer) -> float:
    """R = d / λ  [m²·K/W]"""
    mat = MATERIALS.get(layer.material_key)
    if mat is None:
        raise ValueError(f"Unknown material key: {layer.material_key!r}")
    return layer.thickness_m / mat.lambda_


def element_u_value(element: EnvelopeElement) -> float:
    """
    Compute U-value [W/(m²·K)] for an envelope element.
    Uses override if provided; otherwise sums layer resistances per ISO 6946 §6.
    """
    if element.u_value_override is not None:
        return element.u_value_override

    rsi, rso = surface_resistances(element)
    rt = rsi + rso + sum(layer_resistance(l) for l in element.layers)
    return 1.0 / rt


def element_thermal_mass(element: EnvelopeElement) -> float:
    """
    Effective thermal mass per unit area [J/(m²·K)] of an element.
    ISO 13786 simplified: only layers inside the insulation contribute.
    We use the full layer stack for simplicity (conservative for lightweight elements).
    """
    kappa = 0.0
    for layer in element.layers:
        mat = MATERIALS.get(layer.material_key)
        if mat is None:
            continue
        kappa += mat.rho * mat.cp * layer.thickness_m
    return kappa


def ua_total(elements: list[EnvelopeElement]) -> float:
    """Total heat loss coefficient UA [W/K] (sum of U·A for all elements)."""
    return sum(element_u_value(e) * e.area_m2 for e in elements)


def element_summary(element: EnvelopeElement) -> dict:
    """Return a dict of key metrics for one element (for display)."""
    u = element_u_value(element)
    r_total = 1.0 / u

    layers_info = []
    if element.u_value_override is None:
        for layer in element.layers:
            mat = MATERIALS.get(layer.material_key)
            r = layer_resistance(layer)
            layers_info.append({
                "material": mat.name if mat else layer.material_key,
                "thickness_mm": layer.thickness_m * 1000,
                "lambda": mat.lambda_ if mat else None,
                "R": round(r, 3),
            })

    return {
        "name": element.name,
        "type": element.type.value,
        "orientation": element.orientation.value,
        "area_m2": element.area_m2,
        "U_value": round(u, 3),
        "R_total": round(r_total, 3),
        "UA": round(u * element.area_m2, 2),
        "layers": layers_info,
        "thermal_mass_kJ_m2K": round(element_thermal_mass(element) / 1000, 1),
    }
