"""
In-memory session store: a single dict[model_id, RoomDoc].
Contains element serialisation and the JSON persistence layer
(save_model / load_all_models).
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from ..channels import Budget, Channel
from ..elements import EnvelopeElement, Layer
from ..grouping import GroupResult, group
from ..registry import ELEMENT_TYPES
from .models import (
    BudgetOut,
    ElementOut,
    ElementSpec,
    RoomDoc,
    Signal,
    SignalOut,
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


def signal_to_out(
    signal: "Signal | Any",
    binding_map: dict[str, str | None] | None = None,
) -> SignalOut:
    """
    Serialise a Signal to its API response shape.

    Accepts both ``api.models.Signal`` (from stored doc) and
    ``grouping.Signal`` (from the grouping rule) — both share the same
    identity fields (id, name, kind, role, meta) so duck typing applies.

    Parameters
    ----------
    signal:
        The Signal object to serialise (either flavour).
    binding_map:
        Optional ``{signal_name: binding_string}`` mapping.  When provided,
        the binding for this signal's name is injected into the response.
        When absent, falls back to ``signal.binding`` if the attribute exists
        (i.e. the signal is an ``api.models.Signal`` with a stored binding).
    """
    # Prefer explicit binding_map over the attribute on the signal object.
    if binding_map is not None:
        binding = binding_map.get(signal.name)
    else:
        binding = getattr(signal, "binding", None)
    return SignalOut(
        id=signal.id,
        name=signal.name,
        kind=signal.kind,
        role=signal.role,
        meta=signal.meta,
        binding=binding,
    )


# ── binding helpers ────────────────────────────────────────────────────────────

def binding_map_from_doc(doc: "RoomDoc") -> dict[str, str | None]:
    """
    Build a ``{signal_name: binding_string_or_None}`` lookup from the stored
    signals in *doc*.

    Only signals with a non-None binding are included — callers treat a missing
    key as ``binding=None``.  Used by assembly / document routes to inject
    bindings onto derived Signal objects (which are binding-agnostic).
    """
    return {
        sig.name: sig.binding
        for sig in doc.signals.values()
        if sig.binding is not None
    }


def set_signal_binding(doc: "RoomDoc", signal_name: str, binding: str | None) -> None:
    """
    Set or clear the InfluxDB binding for the Signal named *signal_name* in
    *doc*.

    If *doc.signals* already has an entry for this name (by any sid), updates
    it in place.  Otherwise creates a minimal stub entry — binding information
    must persist even when the signal's other metadata is derived at read time.

    Parameters
    ----------
    doc:
        The in-memory ``RoomDoc`` to mutate.
    signal_name:
        The signal's ODE name (e.g. ``"T_ext"``, ``"G_sol_S"``).
    binding:
        The InfluxDB query string, or ``None`` to clear.
    """
    # Look for an existing stored Signal entry by name.
    for sig in doc.signals.values():
        if sig.name == signal_name:
            sig.binding = binding
            return
    # No existing entry — create a minimal stub so the binding persists.
    # The stub carries only what's needed for persistence; identity fields
    # (kind, role, meta) are left as placeholders and will be overridden
    # by the derived signal at read time.
    sid = doc.next_signal_id()
    doc.signals[sid] = Signal(
        id=sid,
        name=signal_name,
        kind="",    # placeholder — derived at read time
        role="",    # placeholder — derived at read time
        meta={},
        binding=binding,
    )


# ── grouping-rule assembler path (D3) ─────────────────────────────────────────

def doc_to_group(doc: RoomDoc) -> GroupResult:
    """
    Build element objects from ``doc.elements`` and apply the deterministic
    grouping rule (spec 15 / I8).

    Derives modules from element boundaries + treatments.  The returned
    ``GroupResult`` can be converted to a ready-to-build Assembler via
    ``result.to_assembler()``.

    Parameters
    ----------
    doc:
        The in-memory ``RoomDoc`` (elements only).

    Returns
    -------
    GroupResult
        Contains ``derived_modules``, ``signals`` (liveness-correct), and the
        indoor mass element if present.  Call ``.to_assembler().build()`` to
        get a System.
    """
    elements: list[EnvelopeElement] = []
    for eid, spec in doc.elements.items():
        try:
            elements.append(_build_element(spec))
        except Exception:
            pass  # skip malformed elements; assembler will report problems
    return group(elements)


def doc_to_group_with_elem_map(
    doc: RoomDoc,
) -> tuple[GroupResult, dict[int, str]]:
    """
    Like ``doc_to_group``, but also returns a mapping from element object
    identity (``id(elem_obj)``) to doc element ID (e.g. ``"e1"``).

    The element objects in ``GroupResult.derived_modules[i].elements`` are the
    SAME objects built here, so callers can use the returned map to translate
    a ``DerivedModule.elements`` list into doc element IDs.

    Parameters
    ----------
    doc:
        The in-memory ``RoomDoc``.

    Returns
    -------
    (GroupResult, elem_obj_id_to_eid)
        The grouping result plus the identity→doc-eid mapping.
    """
    elements: list[EnvelopeElement] = []
    eids: list[str] = []
    for eid, spec in doc.elements.items():
        try:
            elem = _build_element(spec)
            elements.append(elem)
            eids.append(eid)
        except Exception:
            pass  # skip malformed elements

    gr = group(elements)
    elem_obj_to_eid: dict[int, str] = {id(e): eid for e, eid in zip(elements, eids)}
    return gr, elem_obj_to_eid


# ── assembly mapping helpers ───────────────────────────────────────────────────

def _group_module_key_to_stable_id(gr: GroupResult) -> dict[tuple[str, str | None], str]:
    """
    Map each derived module's ``(type_name, signal_name)`` key to a stable
    string ID suitable for API response ``module_id`` fields.

    The ID is deterministic: ``"{type_name}[{signal_name}]"`` (or
    ``"{type_name}"`` for RoomMass whose signal_name is None).  This lets the
    frontend and tests refer to a specific module without relying on the old
    counter-based ``m0`` / ``m1`` IDs from the routing era.

    The Assembler still tracks modules by their internal name; this mapping
    translates the internal Assembler key (module.name, which is a type-level
    name like "DirectLoss") to the stable per-instance ID.  Because a single
    Assembler may contain multiple DirectLoss instances, we match by iteration
    order (same as ``GroupResult.derived_modules`` → ``to_assembler()``).
    """
    result: dict[tuple[str, str | None], str] = {}
    for dm in gr.derived_modules:
        key = dm.key
        type_name, sig_name = key
        stable_id = f"{type_name}[{sig_name}]" if sig_name is not None else type_name
        result[key] = stable_id
    return result


def _group_assembler_module_name_to_id(gr: GroupResult) -> dict[str, str]:
    """
    Map the Assembler-internal module name (e.g. "DirectLoss", which is
    ``module.name`` — shared by all DirectLoss instances) to the stable
    derived-module ID (e.g. "DirectLoss[T_ext]").

    Because multiple DirectLoss instances share the name "DirectLoss", we
    use order-of-addition (matching ``to_assembler()`` iteration) to
    disambiguate.  The Assembler tracks routes in insertion order, and
    ``_module_name_to_id`` in the routing era used the same position-based
    trick.  Here we build: for the i-th occurrence of "DirectLoss" in the
    assembler's route list, map "DirectLoss" + offset to the corresponding
    derived module's stable ID.

    The return type is ``dict[str, str]``: maps Assembler-level name (possibly
    a positional key like "DirectLoss_1") to the stable grouped ID.  Callers
    must use the same positional scheme as the routing-era ``_module_name_to_id``.
    """
    result: dict[str, str] = {}
    name_seen: dict[str, int] = {}
    key_to_id = _group_module_key_to_stable_id(gr)
    for dm in gr.derived_modules:
        asmname = dm.module.name  # e.g. "DirectLoss", "RoomMass", "SolarGain"
        count = name_seen.get(asmname, 0)
        # Positional key matching the routing-era scheme:
        asm_key = asmname if count == 0 else f"{asmname}_{count}"
        name_seen[asmname] = count + 1
        result[asm_key] = key_to_id[dm.key]
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
          "signals":  {"s0": {"name": "T_ext", "kind": "temperature", ...}, ...},
          "_elem_counter": 3,
          "_signal_counter": 1
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
        "signals": {
            sid: {
                "name": sig.name,
                "kind": sig.kind,
                "role": sig.role,
                "meta": dict(sig.meta),
                # Omit binding key when None to keep old JSON compact.
                **( {"binding": sig.binding} if sig.binding is not None else {} ),
            }
            for sid, sig in doc.signals.items()
        },
        "_elem_counter": doc._elem_counter,
        "_signal_counter": doc._signal_counter,
    }


def roomdoc_from_dict(d: dict) -> RoomDoc:
    """
    Deserialise a dict (from JSON or from ``examples.load_example``) into a
    RoomDoc.

    The ``_elem_counter`` / ``_signal_counter`` fields are optional.  When
    absent (examples dict), the counters are set to max-existing-numeric-suffix
    + 1 so that newly minted IDs never collide with existing ones.

    Old JSON that contains ``modules``, ``routes``, or ``_mod_counter`` keys is
    accepted silently — those keys are simply ignored.
    """
    elements = {
        eid: ElementSpec(type=v["type"], fields=dict(v["fields"]))
        for eid, v in d.get("elements", {}).items()
    }

    signals = {
        sid: Signal(
            id=sid,
            name=v["name"],
            kind=v["kind"],
            role=v["role"],
            meta=dict(v.get("meta", {})),
            # Tolerate absence in old JSON — defaults to None.
            binding=v.get("binding"),
        )
        for sid, v in d.get("signals", {}).items()
    }

    # Recover counters, falling back to max-existing + 1 to avoid ID collisions.
    if "_elem_counter" in d:
        elem_counter = int(d["_elem_counter"])
    else:
        nums = [
            int(eid[1:]) for eid in elements if eid.startswith("e") and eid[1:].isdigit()
        ]
        elem_counter = (max(nums) + 1) if nums else 0

    if "_signal_counter" in d:
        signal_counter = int(d["_signal_counter"])
    else:
        # Fall back to max numeric suffix of s… ids + 1 to avoid ID collisions.
        nums = [
            int(sid[1:]) for sid in signals if sid.startswith("s") and sid[1:].isdigit()
        ]
        signal_counter = (max(nums) + 1) if nums else 0

    doc = RoomDoc(
        uid=d.get("uid", ""),
        name=d.get("name", "Untitled"),
        elements=elements,
        signals=signals,
        _elem_counter=elem_counter,
        _signal_counter=signal_counter,
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
