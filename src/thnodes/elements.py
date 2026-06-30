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
    # D1 boundary/treatment fields (spec 15).
    # treatment: "" = forced default (heavy→thermal_mass, light→simple_loss);
    # "simple_loss" overrides a heavy wall to route via DirectLoss instead of HeavyWall.
    treatment: str = ""

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
    # D1 boundary field (spec 15): room label used when boundary == "adjacent".
    adjacent_room: str = ""

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
    # D1 boundary field (spec 15): label of the adjacent room this partition faces.
    adjacent: str = ""

    def channels(self) -> dict[Channel, Budget]:
        R_layers = sum(_layer_resistance(l.material, l.thickness) for l in self.layers)
        U = 1.0 / (Rsi + R_layers + Rsi)  # both sides interior
        return {Channel.CONDUCTION: Budget(UA=U * self.area)}


@dataclass
class IndoorMass(EnvelopeElement):
    """
    Room geometry element.  Carries the room dimensions and furniture class;
    computes the STORAGE budget (air + furniture thermal mass) from first principles.

    The inherited ``area`` field (from EnvelopeElement) is not meaningful for
    IndoorMass — room geometry is expressed by (a, b, c).  We set ``area`` as a
    non-init, computed field (= a*b, the floor area) so the parent contract is
    satisfied and future code can use it without a separate call.  The registry
    constructs IndoorMass via keyword arguments (a, b, c, furniture), which is
    why ``area`` must not be an __init__ parameter.
    """

    # Room dimensions [m]: width × depth × height
    a: float = 0.0
    b: float = 0.0
    c: float = 0.0
    # Furniture load class: affects the effective thermal mass multiplier
    furniture: Literal["bare", "normal", "heavy"] = "normal"

    # Override area as a computed, non-init field so callers need not supply it.
    area: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # area = floor area; stored so EnvelopeElement.area is always valid.
        self.area = self.a * self.b

    # ── geometry helpers (used by ventilation modules in the future) ──────────

    @property
    def volume(self) -> float:
        """Room air volume [m³]."""
        return self.a * self.b * self.c

    @property
    def floor_area(self) -> float:
        """Floor area [m²] (= a*b)."""
        return self.a * self.b

    @property
    def envelope_area(self) -> float:
        """Total six-face envelope area [m²] = 2*(ab + bc + ac)."""
        a, b, c = self.a, self.b, self.c
        return 2.0 * (a * b + b * c + a * c)

    # ── channel budget ────────────────────────────────────────────────────────

    def channels(self) -> dict[Channel, Budget]:
        """
        Compute the STORAGE budget from room geometry + furniture class.

        Physics:
            V       = a * b * c          [m³]
            C_air   = 1.2 * V * 1005     (rho_air=1.2 kg/m³, cp_air=1005 J/kg/K)
            k       = {bare:1.5, normal:3.0, heavy:6.0}
            C       = C_air * k          [J/K]

        The multiplier k accounts for air + light-to-heavy furniture / surface
        skin contributions that share the same fast time-constant band as the room
        air (per app_proposal §"The ownership rule").
        """
        V = self.a * self.b * self.c
        C_air = 1.2 * V * 1005.0  # rho_air [kg/m³] × cp_air [J/kg/K]
        k = {"bare": 1.5, "normal": 3.0, "heavy": 6.0}[self.furniture]
        C = C_air * k
        return {Channel.STORAGE: Budget(C=C)}


@dataclass
class HeatSource(EnvelopeElement):
    area: float = field(default=0.0)
    # D3 / spec 15: the prescribed flux signal label (e.g. "Q_hvac").
    # A non-empty value routes this HeatSource to SourceFlux[Q_<signal>].
    signal: str = field(default="")

    def channels(self) -> dict[Channel, Budget]:
        return {}
