from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from thermal.api_models import (
    ElementType,
    MaterialOut,
    Orientation,
    RCModelOut,
    Room,
)
from thermal.materials_db import MATERIALS
from thermal.priors import build_priors

try:
    from thermal.data_src.influx import list_signals
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
# RC model prior endpoint
# ---------------------------------------------------------------------------

@app.post("/api/room/rc_model", response_model=RCModelOut)
def post_rc_model(room: Room) -> RCModelOut:
    return build_priors(room)


# ---------------------------------------------------------------------------
# Serve frontend static files
# ---------------------------------------------------------------------------

_FRONTEND = Path(__file__).parent / "frontend"

if _FRONTEND.exists():
    app.mount("/", StaticFiles(directory=_FRONTEND, html=True), name="frontend")
