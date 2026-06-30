from __future__ import annotations

import math

import numpy as np
from fastapi import APIRouter, HTTPException

from ...simulate import forward_sim
from ..models import SimulateIn, SimulateOut
from ..store import get_doc, doc_to_group

router = APIRouter(prefix="/models/{model_id}")


@router.post("/simulate", response_model=SimulateOut)
def post_simulate(model_id: str, body: SimulateIn) -> SimulateOut:
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

    signals_np = {k: np.asarray(v, dtype=float) for k, v in body.signals.items()}

    # Validate signal lengths are consistent
    lengths = {k: len(v) for k, v in signals_np.items()}
    if len(set(lengths.values())) > 1:
        raise HTTPException(
            status_code=400,
            detail=f"Signal arrays must all have the same length. Got: {lengths}",
        )
    if not lengths:
        raise HTTPException(status_code=400, detail="At least one signal array is required.")
    n_steps = next(iter(lengths.values()))

    # Build params: start from prior means, override with request params
    prior_means = {k: math.exp(mu_log) for k, (mu_log, _) in system.priors.items()}
    params = dict(prior_means)
    if body.params:
        params.update(body.params)

    dt = body.dt
    t_span = (0.0, (n_steps - 1) * dt)

    n_states = len(system.state_names)
    if body.x0 is not None:
        if len(body.x0) != n_states:
            raise HTTPException(
                status_code=400,
                detail=f"x0 length {len(body.x0)} != number of states {n_states}.",
            )
        x0 = np.asarray(body.x0, dtype=float)
    else:
        # Default: all states at 20°C
        x0 = np.full(n_states, 20.0)

    try:
        t_out, x_out = forward_sim(system, signals_np, t_span, x0, params, dt=dt)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return SimulateOut(
        t=t_out.tolist(),
        states={name: x_out[i].tolist() for i, name in enumerate(system.state_names)},
    )
