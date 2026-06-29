from __future__ import annotations

import math

import numpy as np
from fastapi import APIRouter, HTTPException

from ...identifiability import identifiability_report
from ..models import IdentOut, ParamStatusOut
from ..store import get_doc, roomboc_to_assembler

router = APIRouter(prefix="/models/{model_id}")

_DEFAULT_DAYS = 7
_DEFAULT_DT = 3600.0  # seconds


def _synthetic_signals(n_hours: int) -> dict[str, np.ndarray]:
    """
    Default 7-day diurnal signals at hourly resolution.
    T_ext: 10°C mean + 5°C amplitude, peaks at 14:00.
    G_sol: half-sine daytime profile, 0 at night, peaks at 500 W/m² at solar noon.
    """
    t = np.arange(n_hours, dtype=float)
    hour_of_day = t % 24
    T_ext = 10.0 + 5.0 * np.cos(2 * math.pi * (hour_of_day - 14.0) / 24.0)
    G_sol = np.where(
        (hour_of_day >= 6) & (hour_of_day <= 18),
        500.0 * np.sin(math.pi * (hour_of_day - 6.0) / 12.0),
        0.0,
    )
    return {"T_ext": T_ext, "G_sol": G_sol}


@router.get("/identifiability", response_model=IdentOut)
def get_identifiability(model_id: str) -> IdentOut:
    doc = get_doc(model_id)

    asm = roomboc_to_assembler(doc)
    system, problems = asm.build(strict=False)
    if system is None:
        raise HTTPException(
            status_code=400,
            detail="Cannot run identifiability: room is incomplete. "
            + "; ".join(p.message for p in problems),
        )

    prior_means = {k: math.exp(mu_log) for k, (mu_log, _) in system.priors.items()}

    n_hours = _DEFAULT_DAYS * 24
    signals = _synthetic_signals(n_hours)
    # Keep only signals the system actually uses
    signals = {k: v for k, v in signals.items() if k in system.signal_names}
    # If the system has signals not in the defaults, fill them with zeros
    for sig in system.signal_names:
        if sig not in signals:
            signals[sig] = np.zeros(n_hours)

    report = identifiability_report(system, prior_means, signals, dt=_DEFAULT_DT)

    param_status = {
        pname: ParamStatusOut(
            status=ps.status,
            reason=ps.reason,
            tau_h=ps.tau_h,
            correlation=ps.correlation,
        )
        for pname, ps in report.param_status.items()
    }
    return IdentOut(param_status=param_status)
