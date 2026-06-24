"""
Assembler — routes a room's `(element, channel)` cells to owning modules and folds
their prior terms into the five RC parameters (physics_model.md §4).

Two responsibilities:
  1. `assemble(room)` — instantiate the current-topology modules and assert the
     exactly-once ownership invariant over every `(element, channel)` cell.
  2. `collect_priors(modules, room)` — aggregate the modules' `PriorTerm`s into an
     `RCModelOut`, reproducing the legacy `build_priors` aggregation exactly.

Cells are keyed by `(element.uid, channel)` — Pydantic element models aren't hashable.
"""

from __future__ import annotations

import math

from .api_models import Room, ContributionOut, ParameterPriorOut, RCModelOut
from .channels import Channel, element_channels
from .state_space import h_int_from_room
from . import modules as M


def assemble(room: Room) -> list[M.FluxModule]:
    """Instantiate the current-topology modules and check exactly-once ownership.

    Routing (current 2R2C topology):
      - RoomMass + Ventilation: room-level, own no element channel
      - window  → WindowLoss (CONDUCTION@T_ext) + SolarGain (SOLAR@transmitted)
      - opaque  → HeavyWall (CONDUCTION@T_ext + SOLAR@sol-air + STORAGE if heavy)
    """
    mods: list[M.FluxModule] = [
        M.RoomMass(floor_area_m2=room.floor_area_m2),
        M.Ventilation(ach=room.ach, volume=room.volume),
    ]

    for elem in room.elements:
        budgets = element_channels(elem)
        if elem.is_opaque:
            mods.append(M.HeavyWall(elem, budgets))
        else:
            mods.append(M.WindowLoss(elem))
            mods.append(M.SolarGain(elem))

    _assert_exactly_once(mods, room)
    return mods


def _assert_exactly_once(mods: list[M.FluxModule], room: Room) -> None:
    """Every offered `(element, channel)` cell is claimed by exactly one module."""
    offered: set[tuple[str, Channel]] = set()
    for elem in room.elements:
        for ch in element_channels(elem):
            offered.add((elem.uid, ch))

    claimed: dict[tuple[str, Channel], int] = {}
    for mod in mods:
        for elem, ch in mod.claims():
            claimed[(elem.uid, ch)] = claimed.get((elem.uid, ch), 0) + 1

    doubled = {k: n for k, n in claimed.items() if n > 1}
    if doubled:
        raise AssertionError(f"channel(s) claimed more than once: {sorted(map(str, doubled))}")

    unclaimed = offered - set(claimed)
    if unclaimed:
        raise AssertionError(f"channel(s) offered but unclaimed: {sorted(map(str, unclaimed))}")

    stray = set(claimed) - offered
    if stray:
        raise AssertionError(f"module claimed channel(s) not offered: {sorted(map(str, stray))}")


# ---------------------------------------------------------------------------
# Prior aggregation
# ---------------------------------------------------------------------------

def _quadrature(terms: list[M.PriorTerm]) -> tuple[float, float, list[ContributionOut]]:
    mu = sum(t.value for t in terms)
    sigma = math.sqrt(sum(t.sigma**2 for t in terms)) if terms else 0.0
    return mu, sigma, [t.contribution for t in terms]


def _area_weighted(terms: list[M.PriorTerm], default: tuple[float, float]):
    """α_eff: area-weighted mean of value, area-weighted quadrature of sigma."""
    area = sum(t.weight for t in terms)
    contribs = [t.contribution for t in terms]
    if area <= 0:
        return default[0], default[1], contribs
    mu = sum(t.value * t.weight for t in terms) / area
    var = sum((t.sigma * t.weight) ** 2 for t in terms)
    return mu, math.sqrt(var) / area, contribs


def collect_priors(mods: list[M.FluxModule], room: Room) -> RCModelOut:
    """Fold module PriorTerms into the five-parameter RCModelOut.

    Ordering note: terms are bucketed in module order, which mirrors the legacy
    per-element loop order, so contribution lists (and JSON snapshots) match.
    """
    by_param: dict[str, list[M.PriorTerm]] = {
        "H_env": [], "H_ve": [], "C_wall": [], "C_room": [], "alpha_eff": [],
    }
    for mod in mods:
        for term in mod.derive_prior():
            by_param[term.param].append(term)

    h_env_mu, h_env_sigma, h_env_contribs = _quadrature(by_param["H_env"])
    h_ve_mu, h_ve_sigma, h_ve_contribs = _quadrature(by_param["H_ve"])
    c_wall_mu, c_wall_sigma, c_wall_contribs = _quadrature(by_param["C_wall"])

    # C_room is a single scalar term.
    c_room_term = by_param["C_room"][0]
    c_room_mu, c_room_sigma = c_room_term.value, c_room_term.sigma
    c_room_contribs = [c_room_term.contribution]

    alpha_mu, alpha_sigma, alpha_contribs = _area_weighted(
        by_param["alpha_eff"], M._ALPHA_DEFAULT
    )

    return RCModelOut(
        H_env=ParameterPriorOut(
            name="Opaque envelope heat loss",
            symbol="H_env",
            unit="W/K",
            description="U·A for opaque elements (walls, roof, floor). Drives sol-air path through C_wall.",
            mu=h_env_mu,
            sigma=h_env_sigma,
            contributions=h_env_contribs,
        ),
        H_ve=ParameterPriorOut(
            name="Ventilation + window heat loss",
            symbol="H_ve",
            unit="W/K",
            description="Direct T_ext→T_room losses: ventilation (ρ·cp·n·V) plus window conduction (U·A). Windows bypass C_wall.",
            mu=h_ve_mu,
            sigma=h_ve_sigma,
            contributions=h_ve_contribs,
        ),
        C_wall=ParameterPriorOut(
            name="Envelope thermal mass",
            symbol="C_wall",
            unit="MJ/K",
            description="Heat stored in heavy envelope layers (brick, concrete…). Drives thermal lag.",
            mu=c_wall_mu,
            sigma=c_wall_sigma,
            contributions=c_wall_contribs,
        ),
        C_room=ParameterPriorOut(
            name="Room interior thermal mass",
            symbol="C_room",
            unit="MJ/K",
            description="Furniture, floor finishes, partition walls. Not described by user — wide prior.",
            mu=c_room_mu,
            sigma=c_room_sigma,
            contributions=c_room_contribs,
        ),
        alpha_eff=ParameterPriorOut(
            name="Outer surface absorptivity",
            symbol="α_eff",
            unit="—",
            description="Area-weighted solar absorptivity of opaque outer surfaces. Drives sol-air temperature.",
            mu=alpha_mu,
            sigma=alpha_sigma,
            contributions=alpha_contribs,
        ),
        H_int=h_int_from_room(room),
    )
