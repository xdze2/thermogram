from dataclasses import dataclass
from enum import Enum, auto


class Channel(Enum):
    CONDUCTION = auto()
    SOLAR_TRANSMISSION = auto()
    SOLAR_OPAQUE = auto()
    STORAGE = auto()


@dataclass
class Budget:
    UA: float | None = None      # W/K
    shgcA: float | None = None   # m²
    alphaA: float | None = None  # m² (absorptance × area)
    C: float | None = None       # J/K
