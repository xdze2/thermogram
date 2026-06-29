"""
Pydantic request/response schemas and the in-memory RoomDoc dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


# ── in-memory session store ────────────────────────────────────────────────────

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
    elements: dict[str, ElementSpec] = field(default_factory=dict)   # id -> spec
    modules: dict[str, ModuleSpec] = field(default_factory=dict)     # id -> spec
    routes: dict[str, list[str]] = field(default_factory=dict)       # module_id -> [element_ids]
    _elem_counter: int = field(default=0, repr=False)
    _mod_counter: int = field(default=0, repr=False)

    def next_element_id(self) -> str:
        eid = f"e{self._elem_counter}"
        self._elem_counter += 1
        return eid

    def next_module_id(self) -> str:
        mid = f"m{self._mod_counter}"
        self._mod_counter += 1
        return mid


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


class ModuleTypeOut(BaseModel):
    type_name: str
    owns: list[str]
    params: list[str]
    fields: list[FieldSchemaOut]


class RegistryOut(BaseModel):
    element_types: list[ElementTypeOut]
    module_types: list[ModuleTypeOut]
    layer_schema: LayerSchemaOut
