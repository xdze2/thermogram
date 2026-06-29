from fastapi import APIRouter, HTTPException, status

from ..models import ElementIn, ElementOut, ElementPatch, ModuleIn, ModuleOut, RoutingIn
from ..models import ElementSpec, ModuleSpec
from ..store import element_to_out, get_doc, module_to_out, save_model

router = APIRouter(prefix="/models/{model_id}")


# ── document ───────────────────────────────────────────────────────────────────

@router.get("/document")
def get_document(model_id: str) -> dict:
    doc = get_doc(model_id)
    elements = [element_to_out(eid, spec) for eid, spec in doc.elements.items()]
    modules = [module_to_out(mid, spec, doc) for mid, spec in doc.modules.items()]
    return {"model_id": model_id, "elements": elements, "modules": modules}


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
    # Remove from any module routing
    for mid in doc.routes:
        doc.routes[mid] = [e for e in doc.routes[mid] if e != eid]
    save_model(model_id)


# ── modules ────────────────────────────────────────────────────────────────────

@router.post("/modules", status_code=status.HTTP_201_CREATED, response_model=ModuleOut)
def add_module(model_id: str, body: ModuleIn) -> ModuleOut:
    from ...registry import MODULE_TYPES
    if body.type not in MODULE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown module type '{body.type}'.")
    doc = get_doc(model_id)
    mid = doc.next_module_id()
    spec = ModuleSpec(type=body.type, fields=dict(body.fields))
    doc.modules[mid] = spec
    doc.routes[mid] = []
    save_model(model_id)
    return module_to_out(mid, spec, doc)


@router.delete("/modules/{mid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_module(model_id: str, mid: str) -> None:
    doc = get_doc(model_id)
    if mid not in doc.modules:
        raise HTTPException(status_code=404, detail=f"Module '{mid}' not found.")
    del doc.modules[mid]
    doc.routes.pop(mid, None)
    save_model(model_id)


@router.put("/modules/{mid}/routing", response_model=ModuleOut)
def put_routing(model_id: str, mid: str, body: RoutingIn) -> ModuleOut:
    doc = get_doc(model_id)
    if mid not in doc.modules:
        raise HTTPException(status_code=404, detail=f"Module '{mid}' not found.")
    for eid in body.element_ids:
        if eid not in doc.elements:
            raise HTTPException(status_code=404, detail=f"Element '{eid}' not found.")
    doc.routes[mid] = list(body.element_ids)
    save_model(model_id)
    return module_to_out(mid, doc.modules[mid], doc)
