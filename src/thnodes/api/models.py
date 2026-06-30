"""
Pydantic request/response schemas and the in-memory RoomDoc dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


# ── in-memory session store ────────────────────────────────────────────────────

# Valid Signal roles and kinds (per spec 15).
# role  ∈ {exterior, ground, adjacent, solar, prescribed}
# kind  ∈ {temperature, irradiance, flux}
SIGNAL_ROLES = frozenset({"exterior", "ground", "adjacent", "solar", "prescribed"})
SIGNAL_KINDS = frozenset({"temperature", "irradiance", "flux"})


@dataclass
class Signal:
    """
    A named boundary input the model couples to (spec 15 §"Signal as a
    first-class object").

    Kept deliberately binding-agnostic: no ``source``/``data``/``binding``
    field — that is a separate future layer.  Grouping depends only on
    Signal *identity* (id, name, kind, role, meta).
    """

    id: str
    name: str
    kind: str   # "temperature" | "irradiance" | "flux"
    role: str   # "exterior" | "ground" | "adjacent" | "solar" | "prescribed"
    meta: dict = field(default_factory=dict)


@dataclass
class ElementSpec:
    type: str
    fields: dict[str, Any]


@dataclass
class ModuleSpec:
    type: str
    fields: dict[str, Any]


@dataclass
class RoomDoc:
    uid: str = field(default="")              # stable server-assigned opaque UID
    name: str = field(default="Untitled")     # mutable human-readable label
    elements: dict[str, ElementSpec] = field(default_factory=dict)   # id -> spec
    modules: dict[str, ModuleSpec] = field(default_factory=dict)     # id -> spec
    # routes: DEPRECATED — slated for removal in D3 once derived-module API lands.
    # Kept here so that /assembly, /simulate, /topology.svg, examples, and tests
    # continue to work until the D3 cutover.
    routes: dict[str, list[str]] = field(default_factory=dict)       # module_id -> [element_ids]
    signals: dict[str, Signal] = field(default_factory=dict)         # id -> Signal
    _elem_counter: int = field(default=0, repr=False)
    _mod_counter: int = field(default=0, repr=False)
    _signal_counter: int = field(default=0, repr=False)

    def next_element_id(self) -> str:
        eid = f"e{self._elem_counter}"
        self._elem_counter += 1
        return eid

    def next_module_id(self) -> str:
        mid = f"m{self._mod_counter}"
        self._mod_counter += 1
        return mid

    def next_signal_id(self) -> str:
        sid = f"s{self._signal_counter}"
        self._signal_counter += 1
        return sid


# ── model-list schemas ────────────────────────────────────────────────────────

class ModelInfo(BaseModel):
    """Lightweight summary returned by GET /api/models and create/rename operations."""
    uid: str
    name: str


class ModelCreateIn(BaseModel):
    name: str = "Untitled"


class ModelRenameIn(BaseModel):
    name: str


class ExampleInfo(BaseModel):
    key: str
    name: str


class ModelFromExampleIn(BaseModel):
    example_key: str
    name: str | None = None


# ── budget sub-schema ──────────────────────────────────────────────────────────

class BudgetOut(BaseModel):
    UA: float | None = None
    shgcA: float | None = None
    alphaA: float | None = None
    C: float | None = None


# ── element schemas ────────────────────────────────────────────────────────────

class ElementIn(BaseModel):
    type: str
    fields: dict[str, Any]


class ElementPatch(BaseModel):
    fields: dict[str, Any]


class ElementOut(BaseModel):
    id: str
    type: str
    label: str
    fields: dict[str, Any]
    budgets: dict[str, BudgetOut]


# ── module schemas ─────────────────────────────────────────────────────────────

class ModuleIn(BaseModel):
    type: str
    fields: dict[str, Any] = {}


class ModuleOut(BaseModel):
    id: str
    type: str
    element_ids: list[str]


class RoutingIn(BaseModel):
    element_ids: list[str]


class DerivedModuleOut(BaseModel):
    """
    Read-only derived module produced by the grouping rule (D3 / spec 15).

    ``id`` is stable within the response: ``"{type}[{signal}]"`` for boundary
    modules, or just ``"{type}"`` for RoomMass (which has no boundary signal).
    ``element_ids`` lists the element IDs whose budgets are claimed by this
    module; this is a computed membership — the user did not route them.
    """
    id: str            # e.g. "DirectLoss[T_ext]", "SolarGain[G_sol_S]", "RoomMass"
    type: str          # ModuleType name, e.g. "DirectLoss"
    signal: str | None  # boundary signal name, e.g. "T_ext"; None for RoomMass
    element_ids: list[str]   # element IDs claimed by this module


# ── assembly schemas ───────────────────────────────────────────────────────────

class OwnershipEntry(BaseModel):
    element_id: str
    element_label: str
    channel: str
    module_id: str


class ContributionOut(BaseModel):
    element_id: str
    element_label: str
    channel: str
    budget_field: str
    value: float


class PriorOut(BaseModel):
    mu_log: float
    sigma_log: float


class ParameterOut(BaseModel):
    name: str
    module_id: str
    prior: PriorOut
    contributions: list[ContributionOut]


class GraphNode(BaseModel):
    id: str
    kind: str  # "room" | "state" | "boundary"


class GraphEdge(BaseModel):
    from_: str = None
    to: str = None
    module_id: str = None

    model_config = {"populate_by_name": True}

    # Use aliases so JSON uses "from" (reserved keyword in Python)
    from_node: str = None
    to_node: str = None

    def model_post_init(self, __context: Any) -> None:
        pass


class ProblemOut(BaseModel):
    kind: str
    message: str
    cell: list[str] | None = None


class GraphOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[dict[str, str | None]]


class AssemblyOut(BaseModel):
    ownership: list[OwnershipEntry]
    parameters: list[ParameterOut]
    states: list[str]
    signals: list[str]
    graph: GraphOut
    problems: list[ProblemOut]
    # D3: required_signals — the set of Signals the derived modules demand.
    # Each entry has name/role/kind/meta so the UI can render the inputs panel
    # without a separate /document fetch.  Derived from the grouping result.
    required_signals: list[SignalOut] = []


# ── simulate schemas ───────────────────────────────────────────────────────────

class SimulateIn(BaseModel):
    signals: dict[str, list[float]]
    x0: list[float] | None = None
    params: dict[str, float] | None = None
    dt: float = 3600.0


class SimulateOut(BaseModel):
    t: list[float]
    states: dict[str, list[float]]


# ── identifiability schemas ────────────────────────────────────────────────────

class ParamStatusOut(BaseModel):
    status: str
    reason: str
    tau_h: float | None = None
    correlation: float | None = None


class IdentOut(BaseModel):
    param_status: dict[str, ParamStatusOut]


# ── signal schemas ─────────────────────────────────────────────────────────────

class SignalOut(BaseModel):
    """Read-only view of a Signal document resource (spec 15)."""
    id: str
    name: str
    kind: str
    role: str
    meta: dict = {}


# ── registry schemas ───────────────────────────────────────────────────────────

class FieldSchemaOut(BaseModel):
    name: str
    type: str
    default: Any = None
    options: list[str] | None = None


class LayerSchemaOut(BaseModel):
    fields: list[FieldSchemaOut]


class ElementTypeOut(BaseModel):
    type_name: str
    fields: list[FieldSchemaOut]
    boundary: dict | None = None
    treatments: list[dict] = []


class ModuleTypeOut(BaseModel):
    type_name: str
    owns: list[str]
    params: list[str]
    fields: list[FieldSchemaOut]


class RegistryOut(BaseModel):
    element_types: list[ElementTypeOut]
    module_types: list[ModuleTypeOut]
    layer_schema: LayerSchemaOut
