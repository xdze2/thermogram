"""
Room and envelope element data models.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class Orientation(str, Enum):
    N  = "N"
    NE = "NE"
    E  = "E"
    SE = "SE"
    S  = "S"
    SW = "SW"
    W  = "W"
    NW = "NW"
    HORIZONTAL = "horizontal"   # roof / floor


class ElementType(str, Enum):
    WALL    = "wall"
    WINDOW  = "window"
    ROOF    = "roof"
    FLOOR   = "floor"
    DOOR    = "door"


# Surface resistances (m²·K/W) per ISO 6946 Table 1
RSI_VERTICAL   = 0.13   # interior, vertical heat flow
RSO_VERTICAL   = 0.04   # exterior, vertical heat flow
RSI_HORIZONTAL_UP   = 0.10
RSO_HORIZONTAL_UP   = 0.04
RSI_HORIZONTAL_DOWN = 0.17
RSO_HORIZONTAL_DOWN = 0.04


@dataclass
class MaterialLayer:
    """One layer in a wall/roof/floor cross-section."""
    material_key: str       # key in MATERIALS dict
    thickness: float        # metres


@dataclass
class EnvelopeElement:
    """A single opaque or glazed element of the building envelope."""
    name: str
    type: ElementType
    orientation: Orientation
    area: float             # m²
    layers: list[MaterialLayer] = field(default_factory=list)
    # For windows / doors a single U-value is often given directly
    u_value_override: float | None = None
    # Solar heat gain coefficient (only for windows, dimensionless 0-1)
    shgc: float = 0.6
    # Is this element in contact with ground (floor/basement wall)?
    is_ground_contact: bool = False
    # Tilt angle from horizontal (0=horizontal, 90=vertical)
    tilt: float = 90.0


@dataclass
class Room:
    """Full room / zone description."""
    name: str
    floor_area: float       # m²
    height: float           # m
    latitude: float         # degrees N
    longitude: float        # degrees E
    altitude: float = 0.0   # m above sea level
    elements: list[EnvelopeElement] = field(default_factory=list)
    # Internal gains (people, equipment, lighting) in W
    internal_gains_w: float = 0.0
    # Ventilation air change rate (1/h)
    ach: float = 0.5
    # Thermal mass effective heat capacity per floor area (kJ/(m²·K))
    # ISO 52016 κ₁ value: light=40, medium=70, heavy=110
    kappa: float = 70.0
    # Set-point temperatures
    t_set_heating: float = 20.0   # °C
    t_set_cooling: float = 26.0   # °C

    @property
    def volume(self) -> float:
        return self.floor_area * self.height
