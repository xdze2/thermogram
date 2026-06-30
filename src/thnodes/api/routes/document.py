from fastapi import APIRouter, HTTPException, status

from ..models import (
    DerivedModuleOut,
    ElementIn,
    ElementOut,
    ElementPatch,
    ElementSpec,
    Sensor,
    SensorIn,
    SensorOut,
    SENSOR_STATES,
    SignalOut,
)
from ..store import (
    _build_element,
    binding_map_from_doc,
    doc_to_group_with_elem_map,
    element_to_out,
    get_doc,
    save_model,
    sensor_to_out,
    set_sensor_binding,
    signal_to_out,
)
from ...data_src.influx import parse_signal

router = APIRouter(prefix="/models/{model_id}")


# ── document ───────────────────────────────────────────────────────────────────

@router.get("/document")
def get_document(model_id: str) -> dict:
    doc = get_doc(model_id)
    elements = [element_to_out(eid, spec) for eid, spec in doc.elements.items()]

    # D3: modules and signals are DERIVED from the grouping rule, not stored
    # in the document.  doc_to_group_with_elem_map returns the same element
    # objects used inside the GroupResult, so we can translate
    # dm.elements → doc element IDs.
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

    # Derived signals (liveness-correct from grouping rule), with stored
    # bindings injected from doc.signals by signal name.
    bmap = binding_map_from_doc(doc)
    signals: list[SignalOut] = [signal_to_out(sig, bmap) for sig in gr.signals]

    sensors = [sensor_to_out(s) for s in doc.sensors.values()]

    return {
        "model_id": model_id,
        "elements": elements,
        "modules": modules,
        "signals": signals,
        "sensors": sensors,
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


# ── sensors ────────────────────────────────────────────────────────────────────

@router.post("/sensors", status_code=status.HTTP_201_CREATED, response_model=SensorOut)
def add_sensor(model_id: str, body: SensorIn) -> SensorOut:
    if body.state not in SENSOR_STATES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown state '{body.state}'. Valid states: {sorted(SENSOR_STATES)}.",
        )
    doc = get_doc(model_id)
    sid = doc.next_sensor_id()
    sensor = Sensor(id=sid, state=body.state, name=body.name or body.state)
    doc.sensors[sid] = sensor
    save_model(model_id)
    return sensor_to_out(sensor)


@router.delete("/sensors/{sensor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sensor(model_id: str, sensor_id: str) -> None:
    doc = get_doc(model_id)
    if sensor_id not in doc.sensors:
        raise HTTPException(status_code=404, detail=f"Sensor '{sensor_id}' not found.")
    del doc.sensors[sensor_id]
    save_model(model_id)


from pydantic import BaseModel as _BaseModel


class _SensorBindingIn(_BaseModel):
    binding: str | None = None


@router.put("/sensors/{sensor_id}/binding", response_model=SensorOut)
def put_sensor_binding(model_id: str, sensor_id: str, body: _SensorBindingIn) -> SensorOut:
    doc = get_doc(model_id)
    if sensor_id not in doc.sensors:
        raise HTTPException(status_code=404, detail=f"Sensor '{sensor_id}' not found.")

    if body.binding is not None:
        try:
            parse_signal(body.binding)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    set_sensor_binding(doc, sensor_id, body.binding)
    save_model(model_id)
    return sensor_to_out(doc.sensors[sensor_id])
