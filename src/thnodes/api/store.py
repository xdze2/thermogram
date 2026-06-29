"""
In-memory session store: a single dict[model_id, RoomDoc].
Also contains the roomboc_to_assembler helper, element/module serialisation,
and the JSON persistence layer (save_model / load_all_models).
"""

from __future__ import annotations

import json
import pathlib
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

# ── persistence directory (can be monkeypatched in tests) ─────────────────────

# Resolve relative to this file: src/thnodes/api/store.py → project root is 3 levels up.
_DEFAULT_USER_DATA = pathlib.Path(__file__).resolve().parents[3] / "user_data"
USER_DATA_DIR: pathlib.Path = _DEFAULT_USER_DATA

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
    # Filter fields to only those declared in the registry for this module type.
    # This ensures old JSON documents with now-removed fields (e.g. "floor_area"
    # on RoomMass) load gracefully while a separate agent updates the examples.
    known_fields = {f["name"] for f in MODULE_TYPES[spec.type].get("fields", [])}
    filtered = {k: v for k, v in spec.fields.items() if k in known_fields}
    return ctor(**filtered)


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

    # Build element objects once, keyed by element id.
    elem_objs: dict[str, EnvelopeElement] = {}
    for eid, spec in doc.elements.items():
        try:
            elem_objs[eid] = _build_element(spec)
        except Exception:
            pass  # skip malformed elements; assembler will report problems

    # Register ALL elements with the assembler so IndoorMass is discoverable
    # for RoomMass auto-pairing even when it is not explicitly routed.
    for elem in elem_objs.values():
        asm.add_element(elem)

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


# ── serialisation: RoomDoc ↔ plain dict ───────────────────────────────────────

def roomdoc_to_dict(doc: RoomDoc) -> dict:
    """
    Serialise a RoomDoc to a JSON-safe dict.

    Shape::

        {
          "uid": "...",
          "name": "Untitled",
          "elements": {"e0": {"type": "OuterWall", "fields": {...}}, ...},
          "modules":  {"m0": {"type": "RoomMass",  "fields": {...}}, ...},
          "routes":   {"m0": ["e0", "e1"], ...},
          "_elem_counter": 3,
          "_mod_counter":  2
        }

    This is also the shape that ``examples.load_example`` returns (minus the
    private counters, which are handled in ``roomdoc_from_dict``).
    """
    return {
        "uid": doc.uid,
        "name": doc.name,
        "elements": {
            eid: {"type": spec.type, "fields": spec.fields}
            for eid, spec in doc.elements.items()
        },
        "modules": {
            mid: {"type": spec.type, "fields": spec.fields}
            for mid, spec in doc.modules.items()
        },
        "routes": dict(doc.routes),
        "_elem_counter": doc._elem_counter,
        "_mod_counter": doc._mod_counter,
    }


def roomdoc_from_dict(d: dict) -> RoomDoc:
    """
    Deserialise a dict (from JSON or from ``examples.load_example``) into a
    RoomDoc.

    The ``_elem_counter`` / ``_mod_counter`` fields are optional.  When absent
    (examples dict), the counters are set to max-existing-numeric-suffix + 1 so
    that newly minted IDs never collide with existing ones.
    """
    elements = {
        eid: ElementSpec(type=v["type"], fields=dict(v["fields"]))
        for eid, v in d.get("elements", {}).items()
    }
    modules = {
        mid: ModuleSpec(type=v["type"], fields=dict(v["fields"]))
        for mid, v in d.get("modules", {}).items()
    }
    routes = {mid: list(eids) for mid, eids in d.get("routes", {}).items()}

    # Recover counters, falling back to max-existing + 1 to avoid ID collisions.
    if "_elem_counter" in d:
        elem_counter = int(d["_elem_counter"])
    else:
        nums = [
            int(eid[1:]) for eid in elements if eid.startswith("e") and eid[1:].isdigit()
        ]
        elem_counter = (max(nums) + 1) if nums else 0

    if "_mod_counter" in d:
        mod_counter = int(d["_mod_counter"])
    else:
        nums = [
            int(mid[1:]) for mid in modules if mid.startswith("m") and mid[1:].isdigit()
        ]
        mod_counter = (max(nums) + 1) if nums else 0

    doc = RoomDoc(
        uid=d.get("uid", ""),
        name=d.get("name", "Untitled"),
        elements=elements,
        modules=modules,
        routes=routes,
        _elem_counter=elem_counter,
        _mod_counter=mod_counter,
    )
    return doc


# ── file I/O ──────────────────────────────────────────────────────────────────

def save_model(uid: str) -> None:
    """
    Persist the model with *uid* from ``_store`` to ``USER_DATA_DIR/{uid}.json``.

    No-ops silently when:
    - *uid* is not in ``_store``
    - The doc's own ``uid`` field is empty (e.g. bare ``RoomDoc()`` created by
      tests that directly seed ``_store`` without going through the models router)
    """
    doc = _store.get(uid)
    if doc is None:
        return
    # Bare RoomDoc() injected by tests (uid="") — do not write to disk.
    if not doc.uid:
        return
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = USER_DATA_DIR / f"{uid}.json"
    path.write_text(json.dumps(roomdoc_to_dict(doc), indent=2), encoding="utf-8")


def delete_model_file(uid: str) -> None:
    """Remove ``USER_DATA_DIR/{uid}.json`` if it exists."""
    path = USER_DATA_DIR / f"{uid}.json"
    if path.exists():
        path.unlink()


def load_all_models() -> None:
    """
    Scan ``USER_DATA_DIR`` for ``*.json`` files and load every model into
    ``_store``.  Called once at application startup.  If the directory is
    missing or empty, ``_store`` remains as-is.
    """
    if not USER_DATA_DIR.is_dir():
        return
    for path in sorted(USER_DATA_DIR.glob("*.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            doc = roomdoc_from_dict(d)
            # Derive uid from filename when not stored in JSON (migration safety).
            if not doc.uid:
                doc.uid = path.stem
            _store[doc.uid] = doc
        except Exception:
            # Corrupt / incompatible file — skip silently rather than crashing at
            # startup.  Operators can delete the bad file manually.
            pass
