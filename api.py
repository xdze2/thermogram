from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

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
# Data fetch endpoint
# ---------------------------------------------------------------------------

@app.get("/api/data")
def get_data(
    signals: list[str] = Query(default=[]),
    start: str = Query(...),
    end: str = Query(...),
) -> dict[str, list[list]]:
    """Fetch time-series for selected signals. Returns {signal: [[iso_ts, value], ...]}."""
    if not _HAS_INFLUX or not signals:
        return {}
    result: dict[str, list[list]] = {}
    for sig in signals:
        try:
            s = fetch_series(sig, start, end)
            pairs = [
                [ts.isoformat(), None if (v != v) else float(v)]
                for ts, v in s.items()
            ]
            result[sig] = pairs
        except Exception:
            result[sig] = []
    return result


# ---------------------------------------------------------------------------
# RC model prior endpoint (kept for backwards compat)
# ---------------------------------------------------------------------------

@app.post("/api/room/rc_model", response_model=RCModelOut)
def post_rc_model(room: Room) -> RCModelOut:
    return build_priors(room)


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


@app.get("/api/studies/{study_id}/data")
def get_study_data(study_id: str) -> dict[str, list[list]]:
    """Fetch live data for the study's data_spec."""
    study = _load_or_raise(study_id)
    spec = study.data_spec
    signals = [v for v in spec.signals.values() if v]
    if not _HAS_INFLUX or not signals or not spec.start or not spec.end:
        return {}
    result: dict[str, list[list]] = {}
    for sig in signals:
        try:
            s = fetch_series(sig, spec.start, spec.end)
            result[sig] = [
                [ts.isoformat(), None if (v != v) else float(v)]
                for ts, v in s.items()
            ]
        except Exception:
            result[sig] = []
    return result


# ---------------------------------------------------------------------------
# Serve frontend static files
# ---------------------------------------------------------------------------

_FRONTEND = Path(__file__).parent / "frontend" / "dist"

if _FRONTEND.exists():
    app.mount("/", StaticFiles(directory=_FRONTEND, html=True), name="frontend")
