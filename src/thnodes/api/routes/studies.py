"""
Study endpoints — run configurations attached to a model.

All endpoints are scoped under /api/models/{model_id}/studies.

A Study bundles a time window, optional signal-binding overrides, optional
parameter overrides, and accumulated results (simulate / fit).  Signal
binding resolution for run endpoints follows the priority:
  1. study.signal_overrides[signal_name]  (if non-null)
  2. model.signals[signal_name].binding   (model-level default)
  3. → 400 "Unbound signal: {name}"

Spec: docs/specs/50_studies.md
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from uuid import uuid4

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Response

from ...data_src import influx as _influx
from ...simulate import forward_sim
from ..models import (
    Study,
    StudyCreateIn,
    StudyOut,
    StudyPatchIn,
    StudyResults,
    StudyResultsOut,
    StudyRunSimulateIn,
    StudyTimeRange,
    StudyTimeRangeOut,
)
from ..store import (
    binding_map_from_doc,
    doc_to_group,
    get_doc,
    save_model,
)

router = APIRouter(prefix="/models/{model_id}/studies")


# ── helpers ───────────────────────────────────────────────────────────────────

def _utcnow() -> str:
    """Return current UTC time as ISO-8601 string with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_study_uid() -> str:
    return "study_" + uuid4().hex[:8]


def _study_to_out(study: Study) -> StudyOut:
    """Convert a Study dataclass to its API response shape."""
    tr_out = None
    if study.time_range is not None:
        tr_out = StudyTimeRangeOut(
            start=study.time_range.start,
            end=study.time_range.end,
            resample=study.time_range.resample,
        )
    results_out = StudyResultsOut(
        simulate=study.results.simulate,
        fit=study.results.fit,
    )
    return StudyOut(
        uid=study.uid,
        model_uid=study.model_uid,
        name=study.name,
        created_at=study.created_at,
        updated_at=study.updated_at,
        time_range=tr_out,
        signal_overrides=dict(study.signal_overrides),
        params=dict(study.params),
        results=results_out,
    )


def _get_study(model_id: str, study_id: str) -> tuple:
    """
    Return (doc, study).  Raises 404 for unknown model or study.
    """
    doc = get_doc(model_id)
    study = doc.studies.get(study_id)
    if study is None:
        raise HTTPException(
            status_code=404,
            detail=f"Study '{study_id}' not found on model '{model_id}'.",
        )
    return doc, study


# ── GET /api/models/{model_id}/studies ───────────────────────────────────────

@router.get("", response_model=list[StudyOut])
def list_studies(model_id: str) -> list[StudyOut]:
    """Return all studies for the model, ordered by created_at ascending."""
    doc = get_doc(model_id)
    studies = sorted(doc.studies.values(), key=lambda s: s.created_at)
    return [_study_to_out(s) for s in studies]


# ── POST /api/models/{model_id}/studies ──────────────────────────────────────

@router.post("", response_model=StudyOut, status_code=201)
def create_study(model_id: str, body: StudyCreateIn) -> StudyOut:
    """Create a new study attached to the model."""
    doc = get_doc(model_id)

    now = _utcnow()
    uid = _new_study_uid()

    # Build time_range from body if provided.
    time_range: StudyTimeRange | None = None
    if body.time_range is not None:
        tr = body.time_range
        # A time_range provided at creation must have at least start and end.
        if tr.start is not None and tr.end is not None:
            time_range = StudyTimeRange(
                start=tr.start,
                end=tr.end,
                resample=tr.resample or "15min",
            )
        # If only partial fields given (e.g. only resample), ignore silently —
        # time_range stays null until both start and end are provided via PATCH.

    study = Study(
        uid=uid,
        model_uid=model_id,
        name=body.name,
        created_at=now,
        updated_at=now,
        time_range=time_range,
        signal_overrides=dict(body.signal_overrides),
        params=dict(body.params),
        results=StudyResults(),
    )
    doc.studies[uid] = study
    save_model(model_id)
    return _study_to_out(study)


# ── GET /api/models/{model_id}/studies/{study_id} ────────────────────────────

@router.get("/{study_id}", response_model=StudyOut)
def get_study(model_id: str, study_id: str) -> StudyOut:
    """Return a single study by ID."""
    _, study = _get_study(model_id, study_id)
    return _study_to_out(study)


# ── PATCH /api/models/{model_id}/studies/{study_id} ──────────────────────────

@router.patch("/{study_id}", response_model=StudyOut)
def patch_study(model_id: str, study_id: str, body: StudyPatchIn) -> StudyOut:
    """
    Partial update of author-controlled fields.

    - ``name`` replaces the current name.
    - ``time_range`` is merged field-by-field (only provided sub-fields change).
    - ``signal_overrides`` and ``params`` are replaced wholesale.
    - ``results`` is never touched by this endpoint.
    """
    doc, study = _get_study(model_id, study_id)

    if body.name is not None:
        study.name = body.name

    if body.time_range is not None:
        tr_patch = body.time_range
        if study.time_range is None:
            # Materialise a new time_range from the patch.
            study.time_range = StudyTimeRange(
                start=tr_patch.start or "",
                end=tr_patch.end or "",
                resample=tr_patch.resample or "15min",
            )
        else:
            # Merge field-by-field.
            if tr_patch.start is not None:
                study.time_range.start = tr_patch.start
            if tr_patch.end is not None:
                study.time_range.end = tr_patch.end
            if tr_patch.resample is not None:
                study.time_range.resample = tr_patch.resample

    if body.signal_overrides is not None:
        study.signal_overrides = dict(body.signal_overrides)

    if body.params is not None:
        study.params = dict(body.params)

    study.updated_at = _utcnow()
    save_model(model_id)
    return _study_to_out(study)


# ── DELETE /api/models/{model_id}/studies/{study_id} ─────────────────────────

@router.delete("/{study_id}", status_code=204)
def delete_study(model_id: str, study_id: str) -> Response:
    """Delete a study."""
    doc, _ = _get_study(model_id, study_id)
    del doc.studies[study_id]
    save_model(model_id)
    return Response(status_code=204)


# ── DELETE /api/models/{model_id}/studies/{study_id}/results ─────────────────

@router.delete("/{study_id}/results", response_model=StudyOut)
def clear_study_results(model_id: str, study_id: str) -> StudyOut:
    """Clear results.simulate and results.fit (both set to null)."""
    doc, study = _get_study(model_id, study_id)
    study.results = StudyResults()
    study.updated_at = _utcnow()
    save_model(model_id)
    return _study_to_out(study)


# ── POST /api/models/{model_id}/studies/{study_id}/run/simulate ──────────────

@router.post("/{study_id}/run/simulate", response_model=StudyOut)
def run_simulate(model_id: str, study_id: str, body: StudyRunSimulateIn) -> StudyOut:
    """
    Resolve effective signal bindings, fetch InfluxDB data for the study's
    time_range, run forward simulation, and write results.simulate.

    Binding resolution priority:
      1. study.signal_overrides[signal_name] if non-null
      2. model.signals[signal_name].binding (model-level default)
      3. → 400 "Unbound signal: {name}"
    """
    doc, study = _get_study(model_id, study_id)

    # Validate time_range is configured.
    if study.time_range is None:
        raise HTTPException(
            status_code=400,
            detail="Cannot run simulation: study time_range is null. "
                   "Set start/end via PATCH before running.",
        )

    tr = study.time_range
    if not tr.start or not tr.end:
        raise HTTPException(
            status_code=400,
            detail="Cannot run simulation: time_range.start or time_range.end is empty.",
        )

    # Build the system from the model's elements.
    gr = doc_to_group(doc)
    asm = gr.to_assembler()
    result = asm.build(strict=False)
    system, problems = result
    if system is None:
        raise HTTPException(
            status_code=400,
            detail="Cannot simulate: room is incomplete. "
                   + "; ".join(p.message for p in problems),
        )

    # Resolve effective bindings: study override → model default.
    model_bmap = binding_map_from_doc(doc)
    required_signal_names = [sig.name for sig in gr.signals]

    effective_bindings: dict[str, str] = {}
    unbound: list[str] = []
    for sig_name in required_signal_names:
        # Priority 1: study override (key present and value non-null).
        if sig_name in study.signal_overrides and study.signal_overrides[sig_name] is not None:
            effective_bindings[sig_name] = study.signal_overrides[sig_name]  # type: ignore[assignment]
        # Priority 2: model-level default.
        elif model_bmap.get(sig_name) is not None:
            effective_bindings[sig_name] = model_bmap[sig_name]  # type: ignore[assignment]
        else:
            unbound.append(sig_name)

    if unbound:
        raise HTTPException(
            status_code=400,
            detail="Unbound signal" + ("s" if len(unbound) > 1 else "") + ": "
                   + ", ".join(unbound),
        )

    # Fetch each signal series from InfluxDB.
    series_by_name: dict[str, pd.Series] = {}
    for sig_name in required_signal_names:
        binding = effective_bindings[sig_name]
        try:
            s = _influx.fetch_series(binding, tr.start, tr.end, tr.resample)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"InfluxDB error fetching signal '{sig_name}' (binding={binding!r}): {exc}",
            )
        if s.empty:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Signal '{sig_name}' (binding={binding!r}) returned no data "
                    f"for the period {tr.start!r} – {tr.end!r}."
                ),
            )
        series_by_name[sig_name] = s

    # Align all series to a common index.
    aligned = pd.DataFrame(series_by_name)
    aligned = aligned.interpolate(method="time", limit=4).ffill(limit=4).bfill(limit=4)

    if aligned.isnull().any().any():
        raise HTTPException(
            status_code=400,
            detail="Some signal series contain NaN values after alignment; cannot simulate.",
        )

    # Convert to numpy arrays in signal order.
    signals_np: dict[str, np.ndarray] = {
        col: aligned[col].to_numpy(dtype=float) for col in aligned.columns
    }
    n_steps = len(aligned)

    # Infer dt from the resample period.
    try:
        freq = pd.tseries.frequencies.to_offset(tr.resample)
        dt = float(pd.Timedelta(freq).total_seconds())
    except Exception:
        if len(aligned.index) >= 2:
            dt = float((aligned.index[1] - aligned.index[0]).total_seconds())
        else:
            dt = 900.0  # default 15 min

    t_span = (0.0, (n_steps - 1) * dt)

    # Build params: prior means overridden by study.params.
    prior_means = {k: math.exp(mu_log) for k, (mu_log, _) in system.priors.items()}
    params = dict(prior_means)
    params.update(study.params)

    # Build x0.
    n_states = len(system.state_names)
    if body.x0 is not None:
        if len(body.x0) != n_states:
            raise HTTPException(
                status_code=400,
                detail=f"x0 length {len(body.x0)} != number of states {n_states}.",
            )
        x0 = np.asarray(body.x0, dtype=float)
    else:
        x0 = np.full(n_states, 20.0)

    try:
        t_out, x_out = forward_sim(system, signals_np, t_span, x0, params, dt=dt)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Fetch sensor observations and align them to aligned.index.
    observations: dict[str, list] = {}
    for sensor in doc.sensors.values():
        if not sensor.binding:
            continue
        try:
            s = _influx.fetch_series(sensor.binding, tr.start, tr.end, tr.resample)
            if s.empty:
                continue
            s = s.reindex(aligned.index).interpolate(method="time", limit=4).ffill(limit=4).bfill(limit=4)
            observations[sensor.name] = s.to_numpy(dtype=float).tolist()
        except Exception:
            continue

    # Write results into the study.
    ran_at = _utcnow()
    study.results = StudyResults(
        simulate={
            "ran_at": ran_at,
            "t": t_out.tolist(),
            "states": {
                name: x_out[i].tolist()
                for i, name in enumerate(system.state_names)
            },
            "observations": observations,
        },
        fit=None,
    )
    study.updated_at = ran_at
    save_model(model_id)
    return _study_to_out(study)
