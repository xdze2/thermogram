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

The physics is assembled from flux modules (`thermal/modules.py`) routed by the
assembler (`thermal/assembler.py`) over each element's channels
(`thermal/channels.py`). This function is the thin public entry point; the per-element
math and aggregation live in those modules. See `docs/physics_model.md`.
"""

from .api_models import Room, RCModelOut
from .assembler import assemble, collect_priors


def build_priors(room: Room) -> RCModelOut:
    """Build all five parameter priors from a Room description."""
    modules = assemble(room)
    return collect_priors(modules, room)
