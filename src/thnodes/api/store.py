"""
In-memory session store: a single dict[model_id, RoomDoc].
Also contains the roomboc_to_assembler helper and element/module serialisation.
"""

from __future__ import annotations

from typing import Any

from ..assembler import Assembler, System
from ..channels import Budget, Channel
from ..elements import EnvelopeElement, Layer
from ..modules import TopologyModule
from ..registry import ELEMENT_TYPES, MODULE_TYPES
from .models import (
    BudgetOut,
    ElementOut,
    ElementSpec,
    ModuleOut,
    ModuleSpec,
    RoomDoc,
)

# Global session store.
_store: dict[str, RoomDoc] = {}


def get_store() -> dict[str, RoomDoc]:
    return _store


def get_doc(model_id: str) -> RoomDoc:
    if model_id not in _store:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found.")
    return _store[model_id]


# ── element construction ───────────────────────────────────────────────────────

def _coerce_layers(raw: Any) -> list[Layer]:
    """Convert list[dict] from JSON to list[Layer]."""
    return [Layer(material=d["material"], thickness=d["thickness"]) for d in raw]


def _build_element(spec: ElementSpec) -> EnvelopeElement:
    ctor = ELEMENT_TYPES[spec.type]["ctor"]
    kwargs = dict(spec.fields)
    if "layers" in kwargs:
        kwargs["layers"] = _coerce_layers(kwargs["layers"])
    return ctor(**kwargs)


def _build_module(spec: ModuleSpec) -> TopologyModule:
    ctor = MODULE_TYPES[spec.type]["ctor"]
    return ctor(**spec.fields)


# ── serialisation ──────────────────────────────────────────────────────────────

def _budget_out(budget: Budget) -> BudgetOut:
    return BudgetOut(UA=budget.UA, shgcA=budget.shgcA, alphaA=budget.alphaA, C=budget.C)


def element_to_out(eid: str, spec: ElementSpec) -> ElementOut:
    elem = _build_element(spec)
    channels = elem.channels()
    budgets: dict[str, BudgetOut] = {}
    for ch, budget in channels.items():
        budgets[ch.name] = _budget_out(budget)
    # Fill zero-budget slots for channels the element doesn't offer
    for ch in Channel:
        if ch.name not in budgets:
            budgets[ch.name] = BudgetOut()
    return ElementOut(
        id=eid,
        type=spec.type,
        label=spec.type,
        fields=spec.fields,
        budgets=budgets,
    )


def module_to_out(mid: str, spec: ModuleSpec, doc: RoomDoc) -> ModuleOut:
    return ModuleOut(
        id=mid,
        type=spec.type,
        element_ids=doc.routes.get(mid, []),
    )


# ── assembler construction ─────────────────────────────────────────────────────

def roomboc_to_assembler(doc: RoomDoc) -> Assembler:
    """Build an Assembler from the current RoomDoc state."""
    asm = Assembler()

    # Build element objects once, keyed by element id
    elem_objs: dict[str, EnvelopeElement] = {}
    for eid, spec in doc.elements.items():
        try:
            elem_objs[eid] = _build_element(spec)
        except Exception:
            pass  # skip malformed elements; assembler will report problems

    for mid, spec in doc.modules.items():
        try:
            mod = _build_module(spec)
        except Exception:
            continue
        element_ids = doc.routes.get(mid, [])
        elements = [elem_objs[eid] for eid in element_ids if eid in elem_objs]
        asm.add_module(mod, elements=elements)

    return asm


# ── assembly mapping helpers ───────────────────────────────────────────────────

def _module_name_to_id(doc: RoomDoc) -> dict[str, str]:
    """
    Map module internal name (e.g. "DirectLoss") to session ID (e.g. "m1").

    Module names are not unique if the same type is added twice, so we build
    the reverse map by position: same iteration order as roomboc_to_assembler.
    We rely on the fact that modules are iterated in insertion order (dict).
    """
    # Build ordered list of (mid, mod_name) as they would be added to assembler.
    result: dict[str, str] = {}
    # Track which module names have been seen so we can handle duplicates.
    name_seen: dict[str, int] = {}
    for mid, spec in doc.modules.items():
        try:
            mod = _build_module(spec)
            mname = mod.name
        except Exception:
            continue
        count = name_seen.get(mname, 0)
        key = mname if count == 0 else f"{mname}_{count}"
        name_seen[mname] = count + 1
        result[key] = mid
    return result


def _elem_label_to_id(doc: RoomDoc) -> dict[str, str]:
    """
    Map element labels (as assigned by Assembler: type-name with counter suffix)
    back to session element IDs.
    """
    result: dict[str, str] = {}
    label_counter: dict[str, int] = {}
    for eid, spec in doc.elements.items():
        base = spec.type
        count = label_counter.get(base, 0)
        label = base if count == 0 else f"{base}_{count}"
        label_counter[base] = count + 1
        result[label] = eid
    return result
