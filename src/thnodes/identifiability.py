"""
Step 1 — Identifiability lens.

Predicts, before fitting, which parameters the data can resolve.
All computation is at prior-mean parameters; no fit is required.

Public API:
    bands_from_system(system, prior_means) -> list[float]   # tau_k in hours
    band_overlap(taus, threshold_decades) -> list[tuple[int, int]]
    input_excitation(signals, taus, dt) -> ExcitationReport
    identifiability_report(system, prior_means, signals, dt) -> IdentReport
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.signal import welch

# Band-overlap threshold: two time constants are "same band" if within this many
# decades.  Placeholder — pin down empirically once real fits run.
_OVERLAP_THRESHOLD_DECADES = 1.0  # TODO: tune empirically


# ── linear-system extraction ───────────────────────────────────────────────────

def _build_A(system: Any, params: dict[str, float]) -> np.ndarray:
    """
    Extract the state-transition matrix A via finite differences of rhs w.r.t. x.

    The star LTI system is autonomous when signals are treated as constants, so
    A[i,j] = d(rhs_i)/d(x_j) evaluated at any equilibrium point (signals cancel).
    We use x=0, signals=0 (only the A matrix matters for eigenvalues).
    """
    n = len(system.state_names)
    signals_zero = {s: 0.0 for s in system.signal_names}
    # Include synthetic signal for HeavyWall
    signals_zero["_T_sol_air"] = 0.0

    x0 = np.zeros(n)
    f0 = system.rhs(0.0, x0, signals_zero, params)

    eps = 1e-4
    A = np.zeros((n, n))
    for j in range(n):
        xp = x0.copy()
        xp[j] += eps
        fp = system.rhs(0.0, xp, signals_zero, params)
        A[:, j] = (fp - f0) / eps
    return A


def bands_from_system(system: Any, prior_means: dict[str, float]) -> list[float]:
    """
    Return the time constants τ_k = -1/Re(λ_k) (in seconds) of the system,
    sorted ascending (fastest first).

    Uses prior_means as parameter values. Eigenvalues with Re(λ) ≥ 0 are
    skipped (would correspond to unstable modes — not expected in a valid topology).
    """
    A = _build_A(system, prior_means)
    eigenvalues = np.linalg.eigvals(A)
    taus = []
    for lam in eigenvalues:
        re = lam.real
        if re < 0:
            taus.append(-1.0 / re)
    return sorted(taus)


# ── band-overlap detection ─────────────────────────────────────────────────────

def band_overlap(
    taus: list[float],
    threshold_decades: float = _OVERLAP_THRESHOLD_DECADES,
) -> list[tuple[int, int]]:
    """
    Return pairs (i, j) of tau indices whose time constants are within
    `threshold_decades` decades of each other (i.e. log10(tau_j/tau_i) < threshold).

    Pairs are returned with i < j.
    """
    overlapping = []
    for i in range(len(taus)):
        for j in range(i + 1, len(taus)):
            ratio = taus[j] / taus[i]   # taus sorted ascending, so ratio ≥ 1
            if math.log10(ratio) < threshold_decades:
                overlapping.append((i, j))
    return overlapping


# ── input excitation ───────────────────────────────────────────────────────────

@dataclass
class BandExcitation:
    """Excitation summary for one time-constant band."""
    tau: float               # band centre time constant (seconds)
    band_freq: float         # 1/(2π τ) in Hz — DISPLAY ONLY; does not gate any verdict.
                             # The lens deliberately uses broadband metrics (has_power +
                             # max_correlation) rather than a power-at-pole-frequency check,
                             # because an integrating thermal node is driven by forcing
                             # faster than its own pole. See docs/TODO.md Step 1 closeout #1.
    has_power: bool          # at least one boundary signal has non-zero variance
    signal_names: list[str]  # which signals are non-constant
    max_correlation: float   # max pairwise |Pearson r| among boundary signals (NaN if <2 sigs)


@dataclass
class ExcitationReport:
    bands: list[BandExcitation]
    signal_names: list[str]


def input_excitation(
    signals: dict[str, np.ndarray],
    taus: list[float],
    dt: float = 3600.0,
) -> ExcitationReport:
    """
    Per band: check whether boundary signals are non-constant and mutually correlated.

    signals: dict of 1-D arrays (same length), representing boundary time series.
    taus: list of time constants in seconds (from bands_from_system).
    dt: sampling interval in seconds (unused here, kept for API consistency).

    Collinearity metric: max pairwise |Pearson r| among all boundary signal pairs.
    Cross-correlation is broadband — it captures the overall linear dependence
    between signals regardless of which frequency band dominates. This is the right
    metric for passive diurnal data where T_ext and G_sol co-vary throughout the day.

    has_power: True if any signal has non-zero variance (i.e. is not constant).
    A constant signal carries no information about any parameter, regardless of τ.
    """
    sig_names = list(signals.keys())
    arrays = [np.asarray(signals[s], dtype=float) for s in sig_names]

    # Identify non-constant signals (std > 0)
    non_const_idx = [i for i, arr in enumerate(arrays) if np.std(arr) > 1e-9]
    has_power_global = len(non_const_idx) > 0
    active_names = [sig_names[i] for i in non_const_idx]

    # Max pairwise |Pearson r| among non-constant signal pairs — computed once,
    # shared across all bands (cross-correlation is not band-specific).
    max_r = float("nan")
    if len(non_const_idx) >= 2:
        max_r = 0.0
        for ki in range(len(non_const_idx)):
            for kj in range(ki + 1, len(non_const_idx)):
                a = arrays[non_const_idx[ki]]
                b = arrays[non_const_idx[kj]]
                r = float(np.corrcoef(a, b)[0, 1])
                max_r = max(max_r, abs(r))

    # Same excitation info applies to every band — collinearity is a property
    # of the input signals, not of the node time constant.
    band_results = []
    for tau in taus:
        f_band = 1.0 / (2.0 * math.pi * tau)
        band_results.append(BandExcitation(
            tau=tau,
            band_freq=f_band,
            has_power=has_power_global,
            signal_names=active_names,
            max_correlation=max_r,
        ))

    return ExcitationReport(bands=band_results, signal_names=sig_names)


# ── identifiability report ─────────────────────────────────────────────────────

_HIGH_CORRELATION_THRESHOLD = 0.7  # |Pearson r| flagged as "correlated inputs"


@dataclass
class ParamStatus:
    status: str          # "resolvable" | "borderline" | "prior_dominated"
    reason: str
    tau_h: float | None = None        # band time constant in hours (None if unassigned)
    correlation: float | None = None  # max pairwise |Pearson r| among boundary signals


@dataclass
class IdentReport:
    param_status: dict[str, ParamStatus]
    taus: list[float]
    overlapping_pairs: list[tuple[int, int]]
    excitation: ExcitationReport


def identifiability_report(
    system: Any,
    prior_means: dict[str, float],
    signals: dict[str, np.ndarray],
    dt: float = 3600.0,
) -> IdentReport:
    """
    Combine pole-band analysis + input excitation into a per-param status dict.

    Status logic:
    - prior_dominated: the param's band has no spectral power in any boundary signal.
    - borderline: band has power but signals are mutually correlated (high coherence),
                  OR the band overlaps with another band (within threshold_decades).
    - resolvable: band is excited by independent (low coherence) signals, no overlap.

    Param-to-band assignment: each param is mapped to the band (tau index) that
    corresponds to its module's time constant. For RoomMass → fastest band (smallest τ);
    for each DelayedConductance module → slowest new band it introduces.
    Since the system is 1-D or 2-D, we use the simple heuristic:
      - C_room → fastest tau
      - C_wall / C_mass / C_slab → remaining taus in order
      - H_*, shgcA → same band as the module they belong to
    """
    taus = bands_from_system(system, prior_means)
    overlapping = band_overlap(taus)
    excitation = input_excitation(signals, taus, dt=dt)

    # Map each param name to a tau index
    param_to_band = _map_params_to_bands(system, taus)

    param_status: dict[str, ParamStatus] = {}
    for pname in system.param_names:
        band_idx = param_to_band.get(pname)
        if band_idx is None:
            # Cannot assign to a band (e.g. shgcA, noise params) — treat as resolvable
            param_status[pname] = ParamStatus("resolvable", "no band dependency identified")
            continue

        exc = excitation.bands[band_idx]
        tau_h = exc.tau / 3600.0
        corr = None if math.isnan(exc.max_correlation) else exc.max_correlation

        if not exc.has_power:
            param_status[pname] = ParamStatus(
                "prior_dominated",
                "all boundary signals are constant",
                tau_h=tau_h,
                correlation=corr,
            )
            continue

        reasons = []
        is_borderline = False

        # Check band overlap
        for (i, j) in overlapping:
            if band_idx in (i, j):
                other = j if band_idx == i else i
                reasons.append(
                    f"band overlap with band τ={taus[other]/3600:.1f}h "
                    f"(within {_OVERLAP_THRESHOLD_DECADES} decade)"
                )
                is_borderline = True

        # Check input collinearity
        if corr is not None and corr >= _HIGH_CORRELATION_THRESHOLD:
            reasons.append(
                f"boundary signals correlated (|r|={corr:.2f})"
            )
            is_borderline = True

        if is_borderline:
            param_status[pname] = ParamStatus(
                "borderline", "; ".join(reasons), tau_h=tau_h, correlation=corr,
            )
        else:
            param_status[pname] = ParamStatus(
                "resolvable", "excited band, independent signals", tau_h=tau_h, correlation=corr,
            )

    return IdentReport(
        param_status=param_status,
        taus=taus,
        overlapping_pairs=overlapping,
        excitation=excitation,
    )


def _map_params_to_bands(system: Any, taus: list[float]) -> dict[str, int]:
    """
    Heuristic mapping of parameter names to band indices.

    Convention (matching the star topology):
    - The fastest band (index 0) belongs to T_room / RoomMass.
    - Remaining bands (indices 1, 2, ...) belong to private states in order.
    - Each module's params are all assigned to the same band as its private state.
    - Memoryless modules (DirectLoss, SolarGain, ...) share the room band (index 0).
    """
    if not taus:
        return {}

    mapping: dict[str, int] = {}

    # Private-state modules get the "extra" bands (indices 1+), in the order
    # private_states were added to the system (which matches state_names order).
    # state_names = [private_states..., T_room]
    private_states = system.state_names[:-1]   # everything except T_room

    # Each private state gets a band slot: slot = index among private states + 1
    # (slot 0 is the room/fast band)
    state_to_band: dict[str, int] = {}
    for k, sname in enumerate(private_states):
        # Assign to band index min(k+1, len(taus)-1) so we never go out of bounds
        state_to_band[sname] = min(k + 1, len(taus) - 1)

    # Walk modules to assign params
    for mod in system._modules:
        if mod.private_states:
            # Module owns a private state → assign its params to that state's band
            # Use the first private state (modules only have one in our catalogue)
            band_idx = state_to_band.get(mod.private_states[0], len(taus) - 1)
        else:
            # Memoryless module → room / fast band
            band_idx = 0

        for pname in mod.params:
            mapping[pname] = band_idx

    return mapping
