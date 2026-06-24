"""
U-value and thermal resistance calculations per ISO 6946:2017.
"""

from .materials_db import MATERIALS
from .api_models import EnvelopeElement, MaterialLayer


def surface_resistances(element: EnvelopeElement) -> tuple[float, float]:
    """Return (Rsi, Rso) in m²·K/W based on element type and heat flow direction."""
    return element.surface_resistances()


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


def ua_total(elements: list[EnvelopeElement]) -> float:
    """Total heat loss coefficient UA [W/K] (sum of U·A for all elements)."""
    return sum(element_u_value(e) * e.area_m2 for e in elements)


