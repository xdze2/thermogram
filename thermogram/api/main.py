"""FastAPI backend for thermogram.

Run:
    uv run uvicorn thermogram.api.main:app --reload --port 8001
"""

from __future__ import annotations

import datetime
import json
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError

from .influx import fetch_series, list_signals
from ..solver.assemble import assemble
from ..solver.simulate import simulate_ivp, simulate_zoh
from ..solver.fit import build_forward, fit_nls, fit_mcmc
from ..solver.identifiability import group_params
from ..solver.physics import expand, model_hash
from ..models import AtomicModel, House, Study

_REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR   = _REPO_ROOT / "data"
HOUSES_DIR = DATA_DIR / "houses"
UI_DIR     = _REPO_ROOT / "ui" / "build"

HOUSES_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="thermogram API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _valid_name(name: str) -> bool:
    return bool(re.fullmatch(r"[a-zA-Z0-9_\-]+", name))


def _load_house_raw(name: str) -> dict:
    path = HOUSES_DIR / f"{name}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"House '{name}' not found")
    return json.loads(path.read_text())


def _validate_house(data: Any, context: str = "body") -> House:
    try:
        return House.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc


def _validate_study(data: Any) -> Study:
    try:
        return Study.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc


def _save_house(name: str, data: dict) -> None:
    path = HOUSES_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _compute_model_hash(house: dict) -> str:
    elements = house.get("elements", []) + house.get("rooms", [])
    return model_hash(elements)


def _attach_study_stale_flags(study: dict, current_hash: str) -> None:
    """Inject _stale_run and _stale_fit flags onto a raw study dict (mutates in place)."""
    run = study.get("run")
    fit = study.get("fit")
    study["_stale_run"] = bool(run and run.get("model_hash") and run["model_hash"] != current_hash)
    study["_stale_fit"] = bool(fit and fit.get("model_hash") and fit["model_hash"] != current_hash)


def _attach_stale_flags(house_raw: dict) -> dict:
    """Inject _model_hash and _stale_* flags onto a raw house dict (mutates and returns)."""
    current_hash = _compute_model_hash(house_raw)
    house_raw["_model_hash"] = current_hash
    for study in house_raw.get("studies", []):
        _attach_study_stale_flags(study, current_hash)
    return house_raw


# ── houses ────────────────────────────────────────────────────────────────────

@app.get("/houses", response_model=list[dict])
def get_houses() -> list[dict]:
    """List all house files with summary info."""
    result = []
    for p in sorted(HOUSES_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text())
            result.append({
                "name":          data.get("name", p.stem),
                "label":         data.get("label", p.stem),
                "n_rooms":       len(data.get("rooms", [])),
                "n_elements":    len(data.get("elements", [])),
                "n_studies":     len(data.get("studies", [])),
                "model_hash":    _compute_model_hash(data),
            })
        except Exception:
            pass
    return result


@app.get("/houses/{name}", response_model=House)
def get_house(name: str) -> House:
    raw = _attach_stale_flags(_load_house_raw(name))
    return _validate_house(raw)


@app.put("/houses/{name}")
def put_house(name: str, body: House) -> dict:
    if not _valid_name(name):
        raise HTTPException(status_code=400, detail="Invalid house name (alphanumeric, _ and - only)")
    raw = body.model_dump(by_alias=True, exclude_none=True)
    raw["name"] = name
    _save_house(name, raw)
    return {"ok": True, "name": name, "model_hash": _compute_model_hash(raw)}


@app.delete("/houses/{name}")
def delete_house(name: str) -> dict:
    if not _valid_name(name):
        raise HTTPException(status_code=400, detail="Invalid house name")
    path = HOUSES_DIR / f"{name}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="House not found")
    path.unlink()
    return {"ok": True, "name": name}


@app.post("/houses")
def create_house(body: House) -> dict:
    """Create a new house. Generates a name from label if not provided."""
    label = (body.label or "").strip() or "new_house"
    name = body.name or re.sub(r"[^a-zA-Z0-9_\-]", "_", label).lower()
    if not _valid_name(name):
        name = "house_" + str(uuid.uuid4())[:8]
    path = HOUSES_DIR / f"{name}.json"
    if path.exists():
        name = name + "_" + str(uuid.uuid4())[:8]
    raw = body.model_dump(by_alias=True, exclude_none=True)
    raw.setdefault("schema_version", "0.3")
    raw.setdefault("rooms", [])
    raw.setdefault("elements", [])
    raw.setdefault("studies", [])
    raw["name"] = name
    _save_house(name, raw)
    return {"ok": True, "name": name}


# ── house expand (preview) ────────────────────────────────────────────────────

@app.post("/houses/{name}/expand")
def post_house_expand(name: str) -> dict:
    """Expand the house into an atomic model (preview, no persist)."""
    house_raw = _load_house_raw(name)
    house = _validate_house(house_raw)
    try:
        atomic_model_raw, expansion_map = expand(
            house.model_dump(by_alias=True, exclude_none=True)
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    validated = AtomicModel.model_validate(atomic_model_raw)
    return {
        "model": validated.model_dump(by_alias=True, exclude_none=True),
        "expansion_map": expansion_map,
    }


# ── studies (embedded in house) ───────────────────────────────────────────────

@app.post("/houses/{name}/studies")
def create_study(name: str, body: dict) -> dict:
    """Create a new study embedded in the house."""
    house_raw = _load_house_raw(name)
    house = _validate_house(house_raw)

    try:
        atomic_model_raw, _ = expand(house.model_dump(by_alias=True, exclude_none=True))
        auto_inputs: dict[str, str] = {}
        auto_observations: dict[str, str] = {}
        for node in atomic_model_raw.get("nodes", []):
            if node["kind"] == "boundary":
                t_src = node.get("T_source")
                if isinstance(t_src, str):
                    auto_inputs[node["id"]] = t_src
            elif node["kind"] == "source":
                sig = node.get("signal")
                if sig:
                    auto_inputs[node["id"]] = sig
        for room in house_raw.get("rooms", []):
            if room.get("role", "mass") == "mass" and room.get("obs_signal"):
                node_id = f"z_{room['id'].replace('-', '')}"
                auto_observations[node_id] = room["obs_signal"]
    except Exception:
        auto_inputs = {}
        auto_observations = {}

    study_id = str(uuid.uuid4())
    label = (body.get("label") or "").strip() or (house.label or study_id)
    study_raw = {
        "id":           study_id,
        "label":        label,
        "type":         body.get("type", "run"),
        "inputs":       auto_inputs,
        "observations": auto_observations,
        "start":        "",
        "end":          "",
        "solver":       "zoh",
    }
    _validate_study(study_raw)

    house_raw.setdefault("studies", []).append(study_raw)
    _save_house(name, house_raw)
    return {"ok": True, "id": study_id}


@app.get("/houses/{name}/studies/{study_id}", response_model=Study)
def get_study(name: str, study_id: str) -> Study:
    house_raw = _load_house_raw(name)
    current_hash = _compute_model_hash(house_raw)
    for s in house_raw.get("studies", []):
        if s["id"] == study_id:
            _attach_study_stale_flags(s, current_hash)
            return _validate_study(s)
    raise HTTPException(status_code=404, detail=f"Study '{study_id}' not found in house '{name}'")


@app.put("/houses/{name}/studies/{study_id}")
def put_study(name: str, study_id: str, body: Study) -> dict:
    house_raw = _load_house_raw(name)
    studies = house_raw.setdefault("studies", [])
    for i, s in enumerate(studies):
        if s["id"] == study_id:
            raw = body.model_dump(by_alias=True, exclude_none=True)
            raw["id"] = study_id
            studies[i] = raw
            _save_house(name, house_raw)
            return {"ok": True, "id": study_id}
    raise HTTPException(status_code=404, detail=f"Study '{study_id}' not found in house '{name}'")


@app.delete("/houses/{name}/studies/{study_id}")
def delete_study(name: str, study_id: str) -> dict:
    house_raw = _load_house_raw(name)
    studies = house_raw.get("studies", [])
    new_studies = [s for s in studies if s["id"] != study_id]
    if len(new_studies) == len(studies):
        raise HTTPException(status_code=404, detail=f"Study '{study_id}' not found in house '{name}'")
    house_raw["studies"] = new_studies
    _save_house(name, house_raw)
    return {"ok": True}


# ── simulate ──────────────────────────────────────────────────────────────────

class SimulateRequest(BaseModel):
    house_name: str
    study_id: str
    start: str
    end: str
    inputs: dict[str, str]        # node_id → signal name
    solver: str = "zoh"           # "ivp" | "zoh"
    dt_minutes: int = 15
    y0_uniform: float | None = None
    param_overrides: dict[str, float] = {}  # node_id.field → value, applied after expand


@app.post("/simulate/run")
def post_simulate_run(req: SimulateRequest) -> dict:
    """Expand the house, fetch inputs from InfluxDB, run the solver, persist result."""
    import numpy as np

    house_raw = _load_house_raw(req.house_name)
    house = _validate_house(house_raw)
    try:
        atomic_model, _ = expand(house.model_dump(by_alias=True, exclude_none=True))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Expand error: {e}") from e

    if req.param_overrides:
        nodes_patched = []
        for n in atomic_model.get("nodes", []):
            n = dict(n)
            for field in ("R", "C", "gain"):
                key = f"{n['id']}.{field}"
                if key in req.param_overrides:
                    n[field] = req.param_overrides[key]
            nodes_patched.append(n)
        atomic_model = {**atomic_model, "nodes": nodes_patched}

    try:
        system = assemble(atomic_model)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Model assembly error: {e}") from e

    inputs: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    errors: dict[str, str] = {}
    for node_id, signal_name in req.inputs.items():
        try:
            s = fetch_series(signal_name, req.start, req.end)
            t_sec = s.index.astype("int64") / 1e9
            inputs[node_id] = (t_sec.to_numpy(), s.to_numpy(dtype=float))
        except Exception as e:
            errors[node_id] = str(e)

    nodes_by_id = {n["id"]: n for n in atomic_model.get("nodes", [])}
    for src_id in system.source_ids:
        if src_id in inputs:
            continue
        node = nodes_by_id.get(src_id, {})
        signal_name = node.get("signal")
        if signal_name:
            try:
                s = fetch_series(signal_name, req.start, req.end)
                t_sec = s.index.astype("int64") / 1e9
                inputs[src_id] = (t_sec.to_numpy(), s.to_numpy(dtype=float))
            except Exception as e:
                errors[src_id] = str(e)

    import datetime as _dt
    t0_sec = _dt.datetime.fromisoformat(req.start).timestamp()
    t1_sec = _dt.datetime.fromisoformat(req.end).timestamp()
    for b_id in system.boundary_ids:
        if b_id in inputs:
            continue
        node = nodes_by_id.get(b_id, {})
        t_src = node.get("T_source")
        if isinstance(t_src, (int, float)):
            t_arr = np.array([t0_sec, t1_sec])
            v_arr = np.array([float(t_src), float(t_src)])
            inputs[b_id] = (t_arr, v_arr)

    if errors:
        raise HTTPException(
            status_code=400,
            detail={"message": "Failed to fetch some signals", "errors": errors},
        )

    y0_array: np.ndarray | None = None
    if req.y0_uniform is not None:
        y0_array = np.full(len(system.mass_ids), req.y0_uniform)

    try:
        if req.solver == "zoh":
            result = simulate_zoh(system, inputs, req.start, req.end, req.dt_minutes, y0=y0_array)
        else:
            result = simulate_ivp(system, inputs, req.start, req.end, y0=y0_array)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Simulation error: {e}") from e

    if not result.success:
        raise HTTPException(status_code=500, detail=f"Solver failed: {result.message}")

    t_iso = [
        datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat()
        for ts in result.t
    ]
    current_hash = _compute_model_hash(house_raw)
    timestamp = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    run_record = {
        "model_hash": current_hash,
        "timestamp":  timestamp,
        "settings": {
            "solver":     req.solver,
            "start":      req.start,
            "end":        req.end,
            "dt_minutes": req.dt_minutes,
            **({"y0_uniform": req.y0_uniform} if req.y0_uniform is not None else {}),
        },
    }
    for study in house_raw.get("studies", []):
        if study["id"] == req.study_id:
            study["run"] = run_record
            break
    _save_house(req.house_name, house_raw)

    return {
        "t": t_iso,
        "nodes": {mid: list(arr) for mid, arr in result.temps.items()},
        "meta": {
            "solver": result.solver,
            "elapsed_s": result.elapsed_s,
            "n_steps": result.n_steps,
            "n_rhs_evals": result.n_rhs_evals,
            "success": result.success,
            "message": result.message,
        },
        "run_record": run_record,
        "atomic_model": atomic_model,
    }


# ── fit ───────────────────────────────────────────────────────────────────────

class PreviewGroupsRequest(BaseModel):
    atomic_model: AtomicModel
    param_keys: list[str]


@app.post("/fit/preview-groups")
def post_fit_preview_groups(req: PreviewGroupsRequest) -> list[list[str]]:
    try:
        return group_params(
            req.atomic_model.model_dump(by_alias=True, exclude_none=True),
            req.param_keys,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class FitRequest(BaseModel):
    house_name: str
    study_id: str
    start: str
    end: str
    inputs: dict[str, str]
    observations: dict[str, str]
    params: dict[str, dict]
    obs_sigma: float = 0.5
    method: str = "nls"
    dt_minutes: int = 15
    y0_uniform: float | None = None


@app.post("/fit/run")
def post_fit_run(req: FitRequest) -> dict:
    """Expand the house, fetch inputs + observations from InfluxDB, run NLS or MCMC fit, persist result."""
    import numpy as np

    house_raw = _load_house_raw(req.house_name)
    house = _validate_house(house_raw)
    try:
        atomic_model, _ = expand(house.model_dump(by_alias=True, exclude_none=True))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Expand error: {e}") from e

    inputs: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    errors: dict[str, str] = {}
    for node_id, signal_name in req.inputs.items():
        try:
            s = fetch_series(signal_name, req.start, req.end)
            t_sec = s.index.astype("int64") / 1e9
            inputs[node_id] = (t_sec.to_numpy(), s.to_numpy(dtype=float))
        except Exception as e:
            errors[node_id] = str(e)

    observations: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for node_id, signal_name in req.observations.items():
        try:
            s = fetch_series(signal_name, req.start, req.end)
            t_sec = s.index.astype("int64") / 1e9
            observations[node_id] = (t_sec.to_numpy(), s.to_numpy(dtype=float))
        except Exception as e:
            errors[node_id] = str(e)

    if errors:
        raise HTTPException(
            status_code=400,
            detail={"message": "Failed to fetch some signals", "errors": errors},
        )

    import datetime as _dt
    _t0_sec = _dt.datetime.fromisoformat(req.start).timestamp()
    _t1_sec = _dt.datetime.fromisoformat(req.end).timestamp()
    _atomic_nodes_by_id = {n["id"]: n for n in atomic_model.get("nodes", [])}
    _fit_system = assemble(atomic_model)
    for b_id in _fit_system.boundary_ids:
        if b_id in inputs:
            continue
        node = _atomic_nodes_by_id.get(b_id, {})
        t_src = node.get("T_source")
        if isinstance(t_src, (int, float)):
            t_arr = np.array([_t0_sec, _t1_sec])
            v_arr = np.array([float(t_src), float(t_src)])
            inputs[b_id] = (t_arr, v_arr)

    fit_config = {
        "params":    req.params,
        "obs_sigma": req.obs_sigma,
        "method":    req.method,
    }

    y0 = None
    if req.y0_uniform is not None:
        system = assemble(atomic_model)
        y0 = np.full(len(system.mass_ids), req.y0_uniform)

    try:
        forward_fn, log_p0, param_keys, groups = build_forward(
            atomic_model, inputs, observations, fit_config,
            req.start, req.end, req.dt_minutes,
            y0=y0,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Model error: {e}") from e

    try:
        if req.method == "mcmc":
            result = fit_mcmc(forward_fn, log_p0, param_keys, fit_config, groups=groups)
            response = {
                "method":          result.method,
                "params_nominal":  result.params_nominal,
                "params_mean":     result.params_mean,
                "params_std":      result.params_std,
                "acceptance_rate": result.acceptance_rate,
                "elapsed_s":       result.elapsed_s,
                "param_groups":    groups,
            }
        else:
            result = fit_nls(forward_fn, log_p0, param_keys, fit_config, groups=groups)
            response = {
                "method":          result.method,
                "params_nominal":  result.params_nominal,
                "params_fitted":   result.params_fitted,
                "params_std":      result.params_std,
                "cost":            result.cost,
                "success":         result.success,
                "message":         result.message,
                "elapsed_s":       result.elapsed_s,
                "n_evals":         result.n_evals,
                "param_groups":    groups,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fit error: {e}") from e

    current_hash = _compute_model_hash(house_raw)
    timestamp = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    fit_record = {
        "model_hash":    current_hash,
        "timestamp":     timestamp,
        "settings": {
            "method":     req.method,
            "start":      req.start,
            "end":        req.end,
            "dt_minutes": req.dt_minutes,
        },
        "result_params": response.get("params_fitted") or response.get("params_mean"),
    }
    for study in house_raw.get("studies", []):
        if study["id"] == req.study_id:
            study["fit"] = fit_record
            break
    _save_house(req.house_name, house_raw)
    response["fit_record"] = fit_record
    response["atomic_model"] = atomic_model

    return response


# ── signals / series ──────────────────────────────────────────────────────────

@app.get("/signals")
def get_signals() -> list[str]:
    try:
        return list_signals()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"InfluxDB unreachable: {e}") from e


@app.get("/series")
def get_series(
    signal: str = Query(..., description="measurement/field?tag=val"),
    start: str = Query(..., description="ISO-8601 start time"),
    end: str = Query(..., description="ISO-8601 end time"),
    resample: str = Query("15min", description="pandas resample offset"),
) -> dict:
    try:
        s = fetch_series(signal, start, end, resample=resample)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"InfluxDB error: {e}") from e

    return {
        "signal": signal,
        "t": [ts.isoformat() for ts in s.index],
        "values": [None if v != v else float(v) for v in s],
    }


# ── static UI (must be last) ──────────────────────────────────────────────────

if UI_DIR.exists():
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
