"""Canonical data contract for thermogram, as Pydantic models.

This module is the **single source of truth** for the shapes that cross the
API boundary and get persisted to ``data/houses/*.json``. They replace the
hand-written JSON Schemas (formerly under ``schema/``) that were documentation
only, validated nowhere, and had drifted from reality — these models instead
reflect what the code (``solver/physics.py``, ``api/main.py``) and the real
house files actually use, and are kept honest by ``tests/test_models.py``.
A JSON Schema can still be derived on demand via ``model_json_schema()``.

Three representation layers, mirroring ``docs/modeling_pipeline.md``:

- **Domain / element layer** — :class:`House`: rooms + envelope elements +
  materials. The user-edited source of truth. The RC model is derived from it,
  never stored.
- **Atomic layer** — :class:`AtomicModel`: the lumped RC graph
  (``expand(house)`` output) the solver assembles. Pure math: mass / boundary /
  resistance / source nodes wired by plain edges.
- **Lumped layer (φ-space)** — :class:`LumpedElement` / :class:`View`: what the
  fit operates on. **Not yet wired** — these are the Step 2/3 contract from
  ``docs/todo.md``; defined here so the shape is pinned before the code lands.

Scope note: these models are the written-down contract. The API routes still
pass raw ``dict`` (see ``api/main.py``); wiring routes to validate against
these models is a follow-up. The solver continues to read plain dicts — call
``.model_dump(by_alias=True, exclude_none=True)`` at the boundary to feed it.

Persisted house JSON also carries computed, ``_``-prefixed fields
(``_model_hash``, ``_stale_run``, ...) injected by the API on read. Models that
may receive those set ``model_config = ConfigDict(extra="allow")`` so loading a
round-tripped house does not fail.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "0.3"

# RFC 4122 UUID v4, as used for room / element ids.
UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
Uuid = Annotated[str, Field(pattern=UUID_PATTERN)]

Orientation = Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

# A signal name: ``measurement/field`` or ``measurement/field?tag=value``.
# Free-form string; the datasource layer parses it. See docs/project_description.md.
SignalName = str


# ── materials ──────────────────────────────────────────────────────────────────


class Material(BaseModel):
    """Physical thermal constants for a homogeneous building material.

    Standalone library entry (``data/materials/*.json``). Inside a house the same
    constants appear as :class:`MaterialEntry` keyed by id under ``house.materials``.
    ``extra="allow"`` tolerates the ``$schema`` self-reference real files carry.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    lambda_: float = Field(alias="lambda", gt=0, description="Thermal conductivity [W/(m·K)].")
    rho: float = Field(gt=0, description="Density [kg/m³].")
    cp: float = Field(gt=0, description="Specific heat capacity [J/(kg·K)].")
    category: Literal[
        "masonry", "insulation", "wood", "concrete", "plaster", "glazing", "other"
    ] | None = None
    source: str | None = None
    notes: str | None = None


class MaterialEntry(BaseModel):
    """A material as embedded in a house's ``materials`` dict (no id/name — the
    dict key is the id)."""

    model_config = ConfigDict(extra="forbid")

    lambda_: float = Field(alias="lambda", gt=0)
    rho: float = Field(gt=0)
    cp: float = Field(gt=0)
    source: str | None = None
    notes: str | None = None


# ── domain / element layer (the House) ──────────────────────────────────────────

Role = Literal["mass", "boundary", "fixed"]


class Room(BaseModel):
    """A thermal zone treated as a single well-mixed air mass."""

    model_config = ConfigDict(extra="allow")  # tolerate computed _ fields on read

    id: Uuid
    label: str
    role: Role = "mass"
    a: float | None = Field(default=None, gt=0, description="Width [m].")
    b: float | None = Field(default=None, gt=0, description="Depth [m].")
    c: float | None = Field(default=None, gt=0, description="Ceiling height [m].")
    furniture_factor: float = Field(
        default=2.5, ge=1.0,
        description="Multiplier on air capacitance for furniture mass. 1.0 = air only.",
    )
    input_signal: SignalName | None = Field(
        default=None, description="Heat source / internal gain in this room [W]."
    )
    obs_signal: SignalName | None = Field(
        default=None, description="Measured indoor temperature [°C]; observation for fitting."
    )


class Layer(BaseModel):
    """A single homogeneous layer in an opaque stack."""

    model_config = ConfigDict(extra="forbid")

    material: str = Field(description="Material id — a key in the house's materials dict.")
    thickness: float = Field(gt=0, description="Layer thickness [m].")


class _ElementBase(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: Uuid
    label: str


class OpaqueElement(_ElementBase):
    """Wall / roof / floor — a layered RC stack between two zones."""

    kind: Literal["opaque"]
    between: tuple[Uuid, Uuid] = Field(description="[interior, exterior] zone ids.")
    a: float = Field(gt=0, description="First dimension [m].")
    b: float = Field(gt=0, description="Second dimension [m].")
    layers: list[Layer] = Field(min_length=1, description="Layers, interior → exterior.")
    orientation: Orientation | None = None
    tilt: float = Field(default=90, ge=0, le=90, description="Tilt from horizontal [°].")
    h_i: float = Field(default=7.7, gt=0, description="Interior convective coeff [W/(m²·K)].")
    h_e: float = Field(default=25.0, gt=0, description="Exterior convective coeff [W/(m²·K)].")
    # NOTE: real data + physics.py use ``solar_absorptance``; the old JSON schema
    # called this ``alpha_solar``. The code key wins.
    solar_absorptance: float = Field(default=0.6, ge=0, le=1)
    no_mass: bool = Field(default=False, description="Treat as a pure resistor (no mass).")


class GlazingElement(_ElementBase):
    """Window / skylight — single U-value + SHGC."""

    kind: Literal["glazing"]
    between: tuple[Uuid, Uuid]
    a: float = Field(gt=0)
    b: float = Field(gt=0)
    U: float = Field(gt=0, description="Overall heat transfer coefficient [W/(m²·K)].")
    SHGC: float | None = Field(default=None, ge=0, le=1, description="Solar heat gain coefficient.")
    orientation: Orientation | None = None
    tilt: float = Field(default=90, ge=0, le=90)


class AirExchangeElement(_ElementBase):
    """Infiltration / ventilation between two zones (no heat recovery)."""

    kind: Literal["air_exchange"]
    between: tuple[Uuid, Uuid]
    ach: float = Field(gt=0, description="Air change rate [h⁻¹].")


class OutdoorElement(_ElementBase):
    """Outdoor boundary zone. Holds location, weather source, and signals."""

    kind: Literal["outdoor"]
    role: Role = "boundary"
    obs_signal: SignalName | None = Field(
        default=None, description="Measured outdoor temperature [°C]."
    )
    # Present in real data + read by physics.py; absent from the old JSON schema.
    solar_signal: SignalName | None = Field(
        default=None, description="Outdoor shortwave solar irradiance signal."
    )
    weather_source: Literal["open_meteo"] | None = None
    location: dict | None = None


class GroundElement(_ElementBase):
    """Ground boundary zone."""

    kind: Literal["ground"]
    role: Role = "boundary"


Element = Annotated[
    Union[
        OpaqueElement,
        GlazingElement,
        AirExchangeElement,
        OutdoorElement,
        GroundElement,
    ],
    Field(discriminator="kind"),
]


class House(BaseModel):
    """Physics-layer description of a building — the source of truth.

    Expands to an :class:`AtomicModel` via ``solver/physics.py``. Studies are
    embedded here; the RC model is never stored. ``extra="allow"`` tolerates the
    computed ``_model_hash`` the API injects on read.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: str = SCHEMA_VERSION
    name: str | None = None
    label: str | None = None
    notes: str | None = None
    materials: dict[str, MaterialEntry] = Field(default_factory=dict)
    rooms: list[Room] = Field(default_factory=list)
    elements: list[Element] = Field(default_factory=list)
    studies: list["Study"] = Field(default_factory=list)


# ── atomic layer (the RC graph: expand() output) ────────────────────────────────


class _AtomicNodeBase(BaseModel):
    model_config = ConfigDict(extra="allow")  # ui_position etc.
    id: str
    label: str | None = None


class MassNode(_AtomicNodeBase):
    """Thermal mass — a state variable (capacitance C)."""

    kind: Literal["mass"]
    C: float = Field(gt=0, description="Thermal capacitance [J/K].")


class BoundaryNode(_AtomicNodeBase):
    """Boundary — fixed/prescribed temperature, not integrated."""

    kind: Literal["boundary"]
    T_source: Union[SignalName, float] = Field(
        description="Forcing: a named input signal, or a fixed value [°C]."
    )


class ResistanceNode(_AtomicNodeBase):
    """Thermal resistance — 2-terminal, wired to exactly two nodes via edges."""

    kind: Literal["resistance"]
    R: float = Field(gt=0, description="Thermal resistance [K/W].")


class SourceNode(_AtomicNodeBase):
    """Heat source — injects Q = gain × signal(t) into a wired mass node."""

    kind: Literal["source"]
    signal: SignalName
    gain: float = Field(gt=0, description="Q = gain × signal.")


AtomicNode = Annotated[
    Union[MassNode, BoundaryNode, ResistanceNode, SourceNode],
    Field(discriminator="kind"),
]


class Edge(BaseModel):
    """A plain wire connecting two nodes — topology only, no attributes."""

    model_config = ConfigDict(extra="forbid")
    from_: str = Field(alias="from")
    to: str


class AtomicModel(BaseModel):
    """The lumped thermal RC network the solver assembles.

    ``C·dT/dt = -L·T + B·u(t)``. Derived from a :class:`House` by ``expand()``;
    not persisted.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: str = SCHEMA_VERSION
    id: str | None = None
    name: str | None = None
    notes: str | None = None
    nodes: list[AtomicNode] = Field(min_length=1)
    edges: list[Edge] = Field(default_factory=list)


# ── lumped layer (φ-space) — NOT YET WIRED (Step 2/3 contract) ───────────────────

CombineRule = Literal[
    "series_sum",        # Req from series R atoms
    "parallel_sum",      # Ceq from parallel C atoms
    "parallel_inv_sum",  # Req from parallel R atoms
    "chain",             # RC_chain: distribute R_total, C_total across n lumps
    "identity",          # T or Q exposed directly
]

LumpedKind = Literal["Req", "Ceq", "RC_chain", "T_boundary", "Q_source"]
FitMode = Literal["free", "fixed", "tied"]


class Prior(BaseModel):
    """A log-normal prior, composed from element data at view-build time.

    The minimal stand-in for the post-v1 ``Belief`` — value + log-space spread,
    no confidence typing yet (see docs/modeling_pipeline.md)."""

    model_config = ConfigDict(extra="forbid")
    nominal: float = Field(gt=0)
    sigma_log: float = Field(ge=0, description="Log-space std; 0 ⇒ effectively fixed.")


class Posterior(BaseModel):
    """Fit result on one lumped element."""

    model_config = ConfigDict(extra="forbid")
    value: float = Field(gt=0)
    sigma_log: float = Field(ge=0)


class LumpedElement(BaseModel):
    """One φ — what the fit operates on. Aggregates atoms via a combine rule.

    See docs/modeling_pipeline.md §"Lumped element". ``RC_chain`` carries two
    free quantities (R_total, C_total); ``n`` sets dynamics fidelity without
    adding parameters.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: LumpedKind
    label: str | None = None
    atoms: list[str] = Field(description="Atomic node ids this lump aggregates.")
    combine: CombineRule
    n: int | None = Field(default=None, ge=1, description="Chain length, RC_chain only.")
    prior: Prior
    prior_C: Prior | None = Field(
        default=None,
        description="C_total prior for RC_chain lumps; prior holds R_total.",
    )
    mode: FitMode = "free"
    tied_to: str | None = None
    realizes: str | None = Field(default=None, description="Element id this realizes.")
    posterior: Posterior | None = None
    posterior_C: Posterior | None = Field(
        default=None,
        description="C_total posterior for RC_chain lumps; posterior holds R_total.",
    )


class View(BaseModel):
    """A choice of lumped elements realizing the house at one abstraction level —
    the φ-space the fit sees. Persisted with a :class:`Study`; atoms recomputed.
    """

    model_config = ConfigDict(extra="allow")
    id: str | None = None
    lumped: list[LumpedElement] = Field(default_factory=list)


# ── studies (embedded in the House) ─────────────────────────────────────────────


class RunResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    model_hash: str | None = None
    timestamp: str | None = None
    settings: dict | None = None


class Study(BaseModel):
    """A run (forward sim) or fit (parameter estimation) configuration + result,
    embedded in the house. The RC model is re-derived on every run; only config +
    results are stored. ``extra="allow"`` tolerates ``_stale_*`` flags and the
    current ``run``/``fit`` result blobs.
    """

    model_config = ConfigDict(extra="allow")

    id: Uuid
    label: str | None = None
    type: Literal["run", "fit"] = "run"
    start: str = ""
    end: str = ""
    inputs: dict[str, SignalName] = Field(default_factory=dict)
    observations: dict[str, SignalName] = Field(default_factory=dict)
    solver: Literal["zoh", "ivp"] = "zoh"
    view: View | None = None  # Step 3: persisted φ-space; None on legacy studies
    run: RunResult | None = None
    fit: RunResult | None = None


# Resolve the forward reference House → Study.
House.model_rebuild()
