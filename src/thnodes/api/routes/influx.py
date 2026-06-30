"""
InfluxDB signal-binding endpoints.

GET  /api/influx/signals
    List all queryable signal names from the connected InfluxDB instance.
    Returns 503 when the database is unreachable.

PUT  /api/models/{model_id}/signals/{signal_name}/binding
    Set or clear the InfluxDB binding for the named signal on the stored doc.
    Body: {"binding": "<measurement/field?tag=val>" | null}
    Validates the binding string with parse_signal (400 on malformed).
    Returns the updated SignalOut.

POST /api/models/{model_id}/simulate-bound
    Run the forward simulation using real InfluxDB data for each bound
    required signal.  Required signals without a binding are rejected (400).
    Body: {"start": "2024-01-01T00:00:00", "end": "2024-01-03T00:00:00",
           "resample": "15min", "x0": [...], "params": {...}}
    Returns the same SimulateOut shape as POST /simulate.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...data_src import influx as _influx
from ...data_src.influx import parse_signal
from ...simulate import forward_sim
from ..models import SignalOut, SimulateOut
from ..store import (
    binding_map_from_doc,
    doc_to_group,
    get_doc,
    save_model,
    set_signal_binding,
    signal_to_out,
)

# Two separate routers — one for the global /influx prefix, one for model-scoped routes.
influx_router = APIRouter(prefix="/influx")
model_router = APIRouter(prefix="/models/{model_id}")


# ── GET /api/influx/signals ───────────────────────────────────────────────────

@influx_router.get("/signals", response_model=list[str])
def get_influx_signals() -> list[str]:
    """
    Return all queryable signal names from the connected InfluxDB instance.

    Signal name format: ``measurement/field?tag=val[&tag2=val2]``

    Returns 503 when the database is unreachable so the frontend can show a
    helpful "DB offline" message rather than crashing.
    """
    try:
        return _influx.list_signals()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"InfluxDB unreachable: {exc}",
        )


# ── PUT /api/models/{model_id}/signals/{signal_name}/binding ─────────────────

class BindingIn(BaseModel):
    """Request body for set/clear binding."""
    binding: str | None = None


@model_router.put("/signals/{signal_name}/binding", response_model=SignalOut)
def put_signal_binding(
    model_id: str, signal_name: str, body: BindingIn
) -> SignalOut:
    """
    Set or clear the InfluxDB binding for *signal_name* on the stored doc.

    - ``{"binding": "measurement/field?tag=val"}`` → sets the binding.
    - ``{"binding": null}`` → clears the binding.

    Validates the binding string with ``parse_signal``; returns 400 on
    malformed input.  Persists the doc after update.

    The named signal must exist as a DERIVED signal on the current model
    (i.e. at least one element references it).  Returns 404 if not found.
    Returns the updated SignalOut.
    """
    doc = get_doc(model_id)

    # Validate the binding string before touching the doc.
    if body.binding is not None:
        try:
            parse_signal(body.binding)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # Confirm the signal exists as a derived signal on this model.
    gr = doc_to_group(doc)
    derived_signal = next(
        (sig for sig in gr.signals if sig.name == signal_name), None
    )
    if derived_signal is None:
        raise HTTPException(
            status_code=404,
            detail=f"Signal '{signal_name}' is not a required signal for model '{model_id}'.",
        )

    # Persist the binding in doc.signals.
    set_signal_binding(doc, signal_name, body.binding)
    save_model(model_id)

    # Return the updated SignalOut with binding injected.
    bmap = binding_map_from_doc(doc)
    return signal_to_out(derived_signal, bmap)


# ── POST /api/models/{model_id}/simulate-bound ───────────────────────────────

class SimulateBoundIn(BaseModel):
    """
    Request body for the InfluxDB-backed simulation.

    ``start`` and ``end`` are ISO-8601 strings (e.g. ``"2024-01-01T00:00:00"``).
    ``resample`` is a pandas offset string (default ``"15min"``).
    ``x0`` and ``params`` follow the same conventions as POST /simulate.
    """
    start: str
    end: str
    resample: str = "15min"
    x0: list[float] | None = None
    params: dict[str, float] | None = None


@model_router.post("/simulate-bound", response_model=SimulateOut)
def post_simulate_bound(model_id: str, body: SimulateBoundIn) -> SimulateOut:
    """
    Run the forward simulation by fetching real InfluxDB data for each
    required signal that has a binding stored on the doc.

    All required signals must be bound.  Missing bindings → 400 listing
    which signals are unbound so the user knows what to configure.

    Uses the same forward_sim path as POST /simulate; time step (dt) is
    inferred from the resample period.
    """
    doc = get_doc(model_id)

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

    bmap = binding_map_from_doc(doc)
    required_signal_names = [sig.name for sig in gr.signals]

    # Check all required signals are bound.
    unbound = [name for name in required_signal_names if bmap.get(name) is None]
    if unbound:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot simulate-bound: the following required signals have no "
                f"InfluxDB binding: {unbound}.  "
                f"Use PUT /models/{model_id}/signals/<name>/binding to bind them."
            ),
        )

    # Fetch each bound signal from InfluxDB.
    series_by_name: dict[str, pd.Series] = {}
    for sig_name in required_signal_names:
        binding = bmap[sig_name]
        try:
            s = _influx.fetch_series(binding, body.start, body.end, body.resample)
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
                    f"for the period {body.start!r} – {body.end!r}."
                ),
            )
        series_by_name[sig_name] = s

    # Align all series to a common index (they share start/end/resample so
    # their indices should match; we use outer join + fill to be safe).
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

    # Infer dt from the resample period via pandas.
    try:
        freq = pd.tseries.frequencies.to_offset(body.resample)
        dt = float(pd.Timedelta(freq).total_seconds())
    except Exception:
        # Fallback: derive from the actual index spacing.
        if len(aligned.index) >= 2:
            dt = float((aligned.index[1] - aligned.index[0]).total_seconds())
        else:
            dt = 900.0  # default 15 min

    t_span = (0.0, (n_steps - 1) * dt)

    # Build params: start from prior means, override with request params.
    prior_means = {k: math.exp(mu_log) for k, (mu_log, _) in system.priors.items()}
    params = dict(prior_means)
    if body.params:
        params.update(body.params)

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

    return SimulateOut(
        t=t_out.tolist(),
        states={name: x_out[i].tolist() for i, name in enumerate(system.state_names)},
    )
