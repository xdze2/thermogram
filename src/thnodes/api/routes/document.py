from fastapi import APIRouter, HTTPException, status

from ..models import (
    DerivedModuleOut,
    ElementIn,
    ElementOut,
    ElementPatch,
    ElementSpec,
    SignalOut,
)
from ..store import (
    _build_element,
    doc_to_group_with_elem_map,
    element_to_out,
    get_doc,
    save_model,
    signal_to_out,
)

router = APIRouter(prefix="/models/{model_id}")


# ── document ───────────────────────────────────────────────────────────────────

@router.get("/document")
def get_document(model_id: str) -> dict:
    doc = get_doc(model_id)
    elements = [element_to_out(eid, spec) for eid, spec in doc.elements.items()]

    # D3: modules and signals are DERIVED from the grouping rule, not from
    # doc.modules / doc.routes (which are vestigial load-compatibility fields).
    # doc_to_group_with_elem_map returns the same element objects used inside
    # the GroupResult, so we can translate dm.elements → doc element IDs.
    gr, elem_obj_to_eid = doc_to_group_with_elem_map(doc)

    # Derived modules: one per (type, signal) key.
    modules: list[DerivedModuleOut] = []
    for dm in gr.derived_modules:
        type_name, sig_name = dm.key
        stable_id = f"{type_name}[{sig_name}]" if sig_name is not None else type_name
        claimed_eids = [
            elem_obj_to_eid[id(e)]
            for e in dm.elements
            if id(e) in elem_obj_to_eid
        ]
        modules.append(DerivedModuleOut(
            id=stable_id,
            type=type_name,
            signal=sig_name,
            element_ids=claimed_eids,
        ))

    # Derived signals (liveness-correct from grouping rule).
    signals: list[SignalOut] = [signal_to_out(sig) for sig in gr.signals]

    return {
        "model_id": model_id,
        "elements": elements,
        "modules": modules,
        "signals": signals,
    }


# ── elements ───────────────────────────────────────────────────────────────────

@router.post("/elements", status_code=status.HTTP_201_CREATED, response_model=ElementOut)
def add_element(model_id: str, body: ElementIn) -> ElementOut:
    from ...registry import ELEMENT_TYPES
    if body.type not in ELEMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown element type '{body.type}'.")
    doc = get_doc(model_id)
    eid = doc.next_element_id()
    spec = ElementSpec(type=body.type, fields=dict(body.fields))
    doc.elements[eid] = spec
    save_model(model_id)
    return element_to_out(eid, spec)


@router.patch("/elements/{eid}", response_model=ElementOut)
def patch_element(model_id: str, eid: str, body: ElementPatch) -> ElementOut:
    doc = get_doc(model_id)
    if eid not in doc.elements:
        raise HTTPException(status_code=404, detail=f"Element '{eid}' not found.")
    spec = doc.elements[eid]
    spec.fields.update(body.fields)
    save_model(model_id)
    return element_to_out(eid, spec)


@router.delete("/elements/{eid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_element(model_id: str, eid: str) -> None:
    doc = get_doc(model_id)
    if eid not in doc.elements:
        raise HTTPException(status_code=404, detail=f"Element '{eid}' not found.")
    del doc.elements[eid]
    # No routing cleanup needed — modules are derived, not stored.
    # Signal GC is handled at read time by the grouping rule (liveness invariant).
    save_model(model_id)


# NOTE: POST /modules, DELETE /modules/{mid}, and PUT /modules/{mid}/routing
# have been RETIRED in D3.  Modules are derived from element boundaries by the
# grouping rule and are no longer authored.  Clients that call these endpoints
# will receive 404 (no matching route).
