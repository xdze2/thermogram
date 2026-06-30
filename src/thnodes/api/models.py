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

# Valid Sensor states (the ODE states a sensor can observe).
# Extensible: future private states (e.g. T_wall) could be observed too.
SENSOR_STATES = frozenset({"T_room"})


@dataclass
class Signal:
    """
    A named boundary input the model couples to (spec 15 §"Signal as a
    first-class object").

    ``binding`` is the optional InfluxDB query string in the form
    ``measurement/field?tag=val[&tag2=val2]`` (e.g.
    ``daikin_aircon/inside_temperature?name=Salon``).  It attaches to
    a Signal's stored representation WITHOUT touching its identity fields
    (id, name, kind, role, meta).  Grouping depends only on Signal *identity*
    and MUST NEVER read ``binding``.
    """

    id: str
    name: str
    kind: str   # "temperature" | "irradiance" | "flux"
    role: str   # "exterior" | "ground" | "adjacent" | "solar" | "prescribed"
    meta: dict = field(default_factory=dict)
    binding: str | None = None


@dataclass
class Sensor:
    """
    An observation channel: a real-world measurement the fit compares against
    a simulated ODE state.

    ``state``   — which ODE state this sensor observes (e.g. "T_room").
    ``name``    — display name (e.g. "T_indoor", default equals state).
    ``binding`` — optional InfluxDB query string (same format as Signal.binding).
    """
    id: str
    state: str           # ODE state observed, e.g. "T_room"
    name: str            # display label
    binding: str | None = None


@dataclass
class ElementSpec:
    type: str
    fields: dict[str, Any]


# ── study dataclasses ─────────────────────────────────────────────────────────

@dataclass
class StudyTimeRange:
    """Time window for a study run."""
    start: str
    end: str
    resample: str = "15min"


@dataclass
class StudyResults:
    """Accumulated results for a study (written only by run endpoints)."""
    simulate: dict | None = None   # {ran_at, t, states} or null
    fit: None = None               # reserved for Step 2–3


@dataclass
class Study:
    """
    A run configuration attached to a model.

    ``signal_overrides`` maps signal names to binding strings (or null to
    explicitly inherit the model default).  Only overridden signals appear
    here; signals absent from the dict fall through to the model-level binding.

    ``params`` holds parameter overrides for the forward simulation.  Any
    parameter not listed here falls back to its prior mean.

    ``results`` is the only field the server writes on a run; all other fields
    are author-controlled and only change on explicit PATCH.
    """
    uid: str
    model_uid: str
    name: str
    created_at: str
    updated_at: str
    time_range: StudyTimeRange | None = None
    signal_overrides: dict[str, str | None] = field(default_factory=dict)
    params: dict[str, float] = field(default_factory=dict)
    results: StudyResults = field(default_factory=StudyResults)


@dataclass
class RoomDoc:
    uid: str = field(default="")              # stable server-assigned opaque UID
    name: str = field(default="Untitled")     # mutable human-readable label
    elements: dict[str, ElementSpec] = field(default_factory=dict)   # id -> spec
    signals: dict[str, Signal] = field(default_factory=dict)         # id -> Signal (bindings only)
    sensors: dict[str, Sensor] = field(default_factory=dict)         # id -> Sensor
    studies: dict[str, Study] = field(default_factory=dict)          # study_uid -> Study
    _elem_counter: int = field(default=0, repr=False)
    _signal_counter: int = field(default=0, repr=False)
    _sensor_counter: int = field(default=0, repr=False)

    def next_element_id(self) -> str:
        eid = f"e{self._elem_counter}"
        self._elem_counter += 1
        return eid

    def next_signal_id(self) -> str:
        sid = f"s{self._signal_counter}"
        self._signal_counter += 1
        return sid

    def next_sensor_id(self) -> str:
        sid = f"sen{self._sensor_counter}"
        self._sensor_counter += 1
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


# ── sensor schemas ─────────────────────────────────────────────────────────────

class SensorIn(BaseModel):
    """Request body for POST /sensors."""
    state: str           # ODE state to observe, e.g. "T_room"
    name: str | None = None   # display name; defaults to state


class SensorOut(BaseModel):
    """Read/write view of a Sensor document resource."""
    id: str
    state: str
    name: str
    binding: str | None = None


# ── signal schemas ─────────────────────────────────────────────────────────────

class SignalOut(BaseModel):
    """Read-only view of a Signal document resource (spec 15).

    ``binding`` carries the optional InfluxDB query string for this signal
    (``measurement/field?tag=val``).  Identity fields (id, name, kind, role,
    meta) are kept separate — grouping never reads ``binding``.
    """
    id: str
    name: str
    kind: str
    role: str
    meta: dict = {}
    binding: str | None = None


# ── study API schemas ─────────────────────────────────────────────────────────

class StudyTimeRangeIn(BaseModel):
    """Time-range sub-object in create/patch bodies."""
    start: str | None = None
    end: str | None = None
    resample: str | None = None


class StudyTimeRangeOut(BaseModel):
    start: str
    end: str
    resample: str


class StudyResultsOut(BaseModel):
    simulate: dict | None = None
    fit: None = None


class StudyOut(BaseModel):
    """API response shape for a Study."""
    uid: str
    model_uid: str
    name: str
    created_at: str
    updated_at: str
    time_range: StudyTimeRangeOut | None = None
    signal_overrides: dict[str, str | None] = {}
    params: dict[str, float] = {}
    results: StudyResultsOut = StudyResultsOut()


class StudyCreateIn(BaseModel):
    """Request body for POST /studies (all fields optional)."""
    name: str = "Untitled study"
    time_range: StudyTimeRangeIn | None = None
    signal_overrides: dict[str, str | None] = {}
    params: dict[str, float] = {}


class StudyPatchIn(BaseModel):
    """Request body for PATCH /studies/{study_id} (all fields optional)."""
    name: str | None = None
    time_range: StudyTimeRangeIn | None = None
    signal_overrides: dict[str, str | None] | None = None
    params: dict[str, float] | None = None


class StudyRunSimulateIn(BaseModel):
    """Request body for POST /studies/{study_id}/run/simulate."""
    x0: list[float] | None = None


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
