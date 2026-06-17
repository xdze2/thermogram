from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

import numpy as np

from thermal.api_models import (
    ElementType,
    MaterialOut,
    Orientation,
    RCModelOut,
    Room,
)
from thermal.materials_db import MATERIALS
from thermal.priors import build_priors
from thermal.study import DataSpec, Study, StudyStub
from thermal.study_store import (
    create_study,
    delete_study,
    duplicate_study,
    list_studies,
    load_study,
    save_study,
)
from thermal.fit import run_fit
from thermal.irradiance import compute_poa, orientations_in_room, orientation_key

try:
    from thermal.data_src.influx import list_signals, fetch_series
    _HAS_INFLUX = True
except Exception:
    _HAS_INFLUX = False

app = FastAPI(title="Thermal nodes API", version="0.1.0")


# ---------------------------------------------------------------------------
# Schema endpoint
# ---------------------------------------------------------------------------

@app.get("/api/schema")
def get_schema() -> dict:
    """Return enum choices the frontend needs to build its dropdowns."""
    return {
        "element_types": [{"value": e.value, "label": e.value.capitalize()} for e in ElementType],
        "orientations": [{"value": o.value, "label": o.value} for o in Orientation],
    }


# ---------------------------------------------------------------------------
# Materials endpoint
# ---------------------------------------------------------------------------

@app.get("/api/materials", response_model=list[MaterialOut])
def get_materials() -> list[MaterialOut]:
    return [
        MaterialOut(
            key=key,
            name=spec.name,
            lambda_W_mK=spec.lambda_,
            rho_kg_m3=spec.rho,
            cp_J_kgK=spec.cp,
            is_heavy=spec.rho > 500,
        )
        for key, spec in MATERIALS.items()
    ]


# ---------------------------------------------------------------------------
# Signals endpoint
# ---------------------------------------------------------------------------

@app.get("/api/signals")
def get_signals() -> list[str]:
    """Return available InfluxDB signal names. Empty list if unreachable."""
    if not _HAS_INFLUX:
        return []
    try:
        return list_signals()
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Studies endpoints
# ---------------------------------------------------------------------------

def _load_or_raise(study_id: str):
    """Load study, raising appropriate HTTP errors for missing or version mismatch."""
    try:
        return load_study(study_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Study not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


class CreateStudyBody(BaseModel):
    name: str = "New study"


class PatchRoomBody(BaseModel):
    room: Room


class PatchDataSpecBody(BaseModel):
    data_spec: DataSpec


class RenameStudyBody(BaseModel):
    name: str


@app.get("/api/studies", response_model=list[StudyStub])
def get_studies() -> list[StudyStub]:
    return list_studies()


@app.post("/api/studies", response_model=Study, status_code=201)
def post_studies(body: CreateStudyBody = CreateStudyBody()) -> Study:
    return create_study(body.name)


@app.get("/api/studies/{study_id}", response_model=Study)
def get_study(study_id: str) -> Study:
    return _load_or_raise(study_id)


@app.delete("/api/studies/{study_id}", status_code=204)
def del_study(study_id: str) -> None:
    try:
        delete_study(study_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Study not found")


@app.post("/api/studies/{study_id}/duplicate", response_model=Study, status_code=201)
def dup_study(study_id: str) -> Study:
    try:
        return duplicate_study(study_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Study not found")


@app.patch("/api/studies/{study_id}/name", response_model=StudyStub)
def patch_study_name(study_id: str, body: RenameStudyBody) -> StudyStub:
    study = _load_or_raise(study_id)
    study.name = body.name
    save_study(study)
    return StudyStub(id=study.id, name=study.name, updated_at=study.updated_at)


@app.patch("/api/studies/{study_id}/room", response_model=RCModelOut)
def patch_study_room(study_id: str, body: PatchRoomBody) -> RCModelOut:
    study = _load_or_raise(study_id)
    study.room = body.room
    study.rc_prior = build_priors(body.room)
    save_study(study)
    return study.rc_prior


@app.patch("/api/studies/{study_id}/data_spec", response_model=DataSpec)
def patch_study_data_spec(study_id: str, body: PatchDataSpecBody) -> DataSpec:
    study = _load_or_raise(study_id)
    study.data_spec = body.data_spec
    save_study(study)
    return study.data_spec


@app.post("/api/studies/{study_id}/fetch_data")
def post_fetch_data(study_id: str) -> dict[str, list[list]]:
    """Pull data from InfluxDB for the study's data_spec and cache it in the study."""
    study = _load_or_raise(study_id)
    spec = study.data_spec
    signals = [v for v in spec.signals.values() if v]
    if not _HAS_INFLUX:
        raise HTTPException(status_code=503, detail="InfluxDB not configured")
    if not signals or not spec.start or not spec.end:
        raise HTTPException(status_code=400, detail="No signals or date range configured")
    result: dict[str, list[list]] = {}
    for sig in signals:
        try:
            s = fetch_series(sig, spec.start, spec.end)
            result[sig] = [
                [ts.isoformat(), None if (v != v) else float(v)]
                for ts, v in s.items()
            ]
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"InfluxDB error for {sig}: {e}")
    study.input_data = result

    # Compute per-orientation POA irradiance if room + irradiance signals are available
    if study.room:
        _append_poa_irradiance(study, result)

    save_study(study)
    return result


def _append_poa_irradiance(study, result: dict[str, list[list]]) -> None:
    """Compute pvlib POA irradiance per orientation and append G_{orient} to result in-place."""
    spec = study.data_spec
    room = study.room
    ghi_key    = spec.signals.get("GHI") or spec.signals.get("Q_sol")  # Q_sol legacy fallback
    direct_key = spec.signals.get("direct")
    diffuse_key = spec.signals.get("diffuse")

    ghi_pairs = (result.get(ghi_key) or []) if ghi_key else []
    if not ghi_pairs:
        return

    timestamps = [p[0] for p in ghi_pairs]
    ghi_arr    = np.array([p[1] if p[1] is not None else 0.0 for p in ghi_pairs], dtype=float)

    direct_map  = {p[0]: p[1] for p in (result.get(direct_key)  or [])} if direct_key else {}
    diffuse_map = {p[0]: p[1] for p in (result.get(diffuse_key) or [])} if diffuse_key else {}
    direct_arr  = np.array([direct_map.get(ts, float("nan"))  for ts in timestamps], dtype=float) if direct_map  else None
    diffuse_arr = np.array([diffuse_map.get(ts, float("nan")) for ts in timestamps], dtype=float) if diffuse_map else None

    orientations = orientations_in_room(room)
    poa = compute_poa(
        lat=room.latitude,
        lon=room.longitude,
        timestamps=timestamps,
        ghi=ghi_arr,
        direct=direct_arr,
        diffuse=diffuse_arr,
        orientations=orientations,
    )
    for orient, G_arr in poa.items():
        result[f"G_{orient}"] = [[ts, round(float(v), 2)] for ts, v in zip(timestamps, G_arr)]


@app.post("/api/studies/{study_id}/fit")
def post_fit(study_id: str) -> dict:
    """Run MAP fit using cached input_data and store fit_result in study."""
    study = _load_or_raise(study_id)
    if not study.input_data:
        raise HTTPException(status_code=400, detail="No cached input data — run fetch_data first")
    if not study.rc_prior:
        raise HTTPException(status_code=400, detail="No RC prior — define room first")
    if not study.room:
        raise HTTPException(status_code=400, detail="No room definition")

    spec = study.data_spec
    t_int_key = spec.signals.get("T_int")
    t_ext_key = spec.signals.get("T_ext")

    if not t_int_key or t_int_key not in study.input_data:
        raise HTTPException(status_code=400, detail="T_int signal not in cached data")
    if not t_ext_key or t_ext_key not in study.input_data:
        raise HTTPException(status_code=400, detail="T_ext signal not in cached data")

    # Align all series on T_int timestamps
    t_int_pairs = study.input_data[t_int_key]
    t_ext_pairs = study.input_data[t_ext_key]

    timestamps = [p[0] for p in t_int_pairs]
    T_obs = np.array([p[1] for p in t_int_pairs], dtype=float)
    T_ext_map = {p[0]: p[1] for p in t_ext_pairs}
    T_ext_arr = np.array([T_ext_map.get(ts, float("nan")) for ts in timestamps], dtype=float)

    # Build area-weighted G_opaque from per-orientation POA irradiance (computed at fetch time)
    from thermal.state_space import opaque_elements
    opaque_elems = opaque_elements(study.room)
    total_opaque_area = sum(e.area_m2 for e in opaque_elems)
    G_opaque = np.zeros(len(timestamps))
    if total_opaque_area > 0:
        for elem in opaque_elems:
            g_key = f"G_{orientation_key(elem)}"
            if g_key in study.input_data:
                g_map = {p[0]: p[1] for p in study.input_data[g_key]}
                g_arr = np.array([g_map.get(ts, 0.0) for ts in timestamps], dtype=float)
                g_arr = np.where(np.isnan(g_arr), 0.0, g_arr)
                G_opaque += (elem.area_m2 / total_opaque_area) * g_arr

    # Remove rows with NaN T_obs or T_ext
    mask = ~(np.isnan(T_obs) | np.isnan(T_ext_arr))
    timestamps_clean = [ts for ts, m in zip(timestamps, mask) if m]
    T_obs = T_obs[mask]
    T_ext_arr = T_ext_arr[mask]
    G_opaque = G_opaque[mask]

    if len(T_obs) < 10:
        raise HTTPException(status_code=400, detail=f"Too few valid observations ({len(T_obs)})")

    # Infer dt from timestamp spacing (assume uniform)
    from datetime import datetime
    ts_dt = [datetime.fromisoformat(t) for t in timestamps_clean[:2]]
    dt = (ts_dt[1] - ts_dt[0]).total_seconds() if len(ts_dt) >= 2 else 3600.0

    Q_room = np.zeros(len(T_obs))  # no Q_int; Q_sol_win not yet separated

    fit = run_fit(
        prior=study.rc_prior,
        dt=dt,
        T_ext=T_ext_arr,
        G_opaque=G_opaque,
        Q_room=Q_room,
        T_obs=T_obs,
        timestamps=timestamps_clean,
    )
    study.fit_result = fit.to_dict()
    save_study(study)
    return study.fit_result


@app.get("/api/studies/{study_id}/fit")
def get_fit(study_id: str) -> dict:
    """Return cached fit_result, or 404 if not yet run."""
    study = _load_or_raise(study_id)
    if not study.fit_result:
        raise HTTPException(status_code=404, detail="No fit result yet")
    return study.fit_result


# ---------------------------------------------------------------------------
# Serve frontend static files
# ---------------------------------------------------------------------------

_FRONTEND = Path(__file__).parent / "frontend" / "dist"

if _FRONTEND.exists():
    app.mount("/", StaticFiles(directory=_FRONTEND, html=True), name="frontend")
