from dataclasses import dataclass, field
from typing import Literal

from .channels import Budget, Channel
from .materials import is_heavy, materials_db

# ISO 6946 surface resistances [m²·K/W]
Rsi = 0.13
Rse = 0.04


def _layer_resistance(material: str, thickness: float) -> float:
    _, lam, _ = materials_db[material]
    return thickness / lam


def _layer_capacity(material: str, thickness: float, area: float) -> float:
    rho, _, cp = materials_db[material]
    return rho * cp * thickness * area


@dataclass
class Layer:
    material: str
    thickness: float  # m


@dataclass
class EnvelopeElement:
    area: float  # m²

    def channels(self) -> dict[Channel, Budget]:
        raise NotImplementedError


@dataclass
class OuterWall(EnvelopeElement):
    orientation: str
    layers: list[Layer]
    alpha: float = 0.6  # solar absorptance of outer surface

    def channels(self) -> dict[Channel, Budget]:
        R_layers = sum(_layer_resistance(l.material, l.thickness) for l in self.layers)
        U = 1.0 / (Rsi + R_layers + Rse)
        C_heavy = sum(
            _layer_capacity(l.material, l.thickness, self.area)
            for l in self.layers
            if is_heavy(materials_db[l.material][0])
        )
        budgets: dict[Channel, Budget] = {
            Channel.CONDUCTION: Budget(UA=U * self.area),
        }
        if C_heavy > 0:
            # SOLAR_OPAQUE only offered by heavy walls (consumed by HeavyWall module).
            # DEFERRED: light-wall sol-air (DirectLoss should shift T_ext → T_sa via
            # solar_boundary); skip for now to keep the happy path warning-free.
            budgets[Channel.STORAGE] = Budget(C=C_heavy)
            budgets[Channel.SOLAR_OPAQUE] = Budget(alphaA=self.alpha * self.area)
        return budgets


@dataclass
class Window(EnvelopeElement):
    orientation: str
    U: float   # W/(m²·K)
    shgc: float

    def channels(self) -> dict[Channel, Budget]:
        return {
            Channel.CONDUCTION: Budget(UA=self.U * self.area),
            Channel.SOLAR_TRANSMISSION: Budget(shgcA=self.shgc * self.area),
        }


@dataclass
class Floor(EnvelopeElement):
    boundary: Literal["ground", "adjacent", "exposed"]
    layers: list[Layer]

    def channels(self) -> dict[Channel, Budget]:
        R_layers = sum(_layer_resistance(l.material, l.thickness) for l in self.layers)
        U = 1.0 / (Rsi + R_layers + Rse)
        C_heavy = sum(
            _layer_capacity(l.material, l.thickness, self.area)
            for l in self.layers
            if is_heavy(materials_db[l.material][0])
        )
        budgets: dict[Channel, Budget] = {
            Channel.CONDUCTION: Budget(UA=U * self.area),
        }
        if C_heavy > 0:
            budgets[Channel.STORAGE] = Budget(C=C_heavy)
        return budgets


@dataclass
class Partition(EnvelopeElement):
    layers: list[Layer]

    def channels(self) -> dict[Channel, Budget]:
        R_layers = sum(_layer_resistance(l.material, l.thickness) for l in self.layers)
        U = 1.0 / (Rsi + R_layers + Rsi)  # both sides interior
        return {Channel.CONDUCTION: Budget(UA=U * self.area)}


@dataclass
class IndoorMass(EnvelopeElement):
    C: float  # J/K, user-specified lumped capacity

    def channels(self) -> dict[Channel, Budget]:
        return {Channel.STORAGE: Budget(C=self.C)}


@dataclass
class HeatSource(EnvelopeElement):
    area: float = field(default=0.0)

    def channels(self) -> dict[Channel, Budget]:
        return {}
