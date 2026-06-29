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
from scipy.signal import coherence, welch

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
    band_freq: float         # 1/(2π τ) in Hz
    has_power: bool          # boundary signals have spectral power near this freq
    signal_names: list[str]  # which signals are relevant
    max_coherence: float     # max pairwise coherence among signals at band freq (NaN if <2 sigs)


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
    Per band: check spectral power and pairwise coherence of boundary signals.

    signals: dict of 1-D arrays (same length), representing boundary time series.
    taus: list of time constants in seconds (from bands_from_system).
    dt: sampling interval in seconds.

    Power threshold: band is "excited" if any signal has power > 1% of its
    total power near the band frequency (within ±0.5 decades).
    """
    sig_names = list(signals.keys())
    arrays = [np.asarray(signals[s], dtype=float) for s in sig_names]
    n_sig = len(arrays)
    fs = 1.0 / dt

    # Compute power spectral densities once
    psds = []
    freqs_ref = None
    for arr in arrays:
        f, psd = welch(arr, fs=fs, nperseg=min(256, len(arr) // 4 or 1))
        if freqs_ref is None:
            freqs_ref = f
        psds.append(psd)

    band_results = []
    for tau in taus:
        f_band = 1.0 / (2.0 * math.pi * tau)

        # Find frequency bin closest to the band frequency
        if freqs_ref is not None and len(freqs_ref) > 1:
            idx = int(np.argmin(np.abs(freqs_ref - f_band)))
        else:
            idx = 0

        # Power check: signal has "power in band" if its PSD at f_band is
        # > 1% of total PSD (integrated).  Signals with zero variance are skipped.
        has_power = False
        active_signals: list[str] = []
        for k, (psd, name) in enumerate(zip(psds, sig_names)):
            total_power = np.trapezoid(psd, freqs_ref) if freqs_ref is not None else 1.0
            if total_power < 1e-12:
                continue  # constant signal, no excitation
            band_power_fraction = psd[idx] / (total_power / len(freqs_ref) if freqs_ref is not None else 1.0)
            if band_power_fraction > 0.01:
                has_power = True
                active_signals.append(name)

        # Pairwise coherence at band frequency between all active signal pairs
        max_coh = float("nan")
        if n_sig >= 2 and freqs_ref is not None:
            max_coh = 0.0
            for i in range(n_sig):
                for j in range(i + 1, n_sig):
                    f_coh, cxy = coherence(
                        arrays[i], arrays[j], fs=fs,
                        nperseg=min(256, len(arrays[i]) // 4 or 1),
                    )
                    if len(f_coh) > 1:
                        coh_idx = int(np.argmin(np.abs(f_coh - f_band)))
                        max_coh = max(max_coh, float(cxy[coh_idx]))

        band_results.append(BandExcitation(
            tau=tau,
            band_freq=f_band,
            has_power=has_power,
            signal_names=active_signals,
            max_coherence=max_coh,
        ))

    return ExcitationReport(bands=band_results, signal_names=sig_names)


# ── identifiability report ─────────────────────────────────────────────────────

_HIGH_COHERENCE_THRESHOLD = 0.7   # magnitude-squared coherence flagged as "correlated"


@dataclass
class ParamStatus:
    status: str          # "resolvable" | "borderline" | "prior_dominated"
    reason: str


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

        if not exc.has_power:
            param_status[pname] = ParamStatus(
                "prior_dominated",
                f"no spectral power in boundary signals at band τ={exc.tau/3600:.1f}h",
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
        if not math.isnan(exc.max_coherence) and exc.max_coherence >= _HIGH_COHERENCE_THRESHOLD:
            reasons.append(
                f"boundary signals correlated (coherence={exc.max_coherence:.2f}) "
                f"at band τ={exc.tau/3600:.1f}h"
            )
            is_borderline = True

        if is_borderline:
            param_status[pname] = ParamStatus("borderline", "; ".join(reasons))
        else:
            param_status[pname] = ParamStatus("resolvable", "excited band, low coherence")

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
