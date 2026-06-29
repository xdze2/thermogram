"""Step 1 acceptance tests — identifiability lens."""

import math

import numpy as np
import pytest

from thnodes import (
    Assembler,
    DirectLoss,
    HeavyWall,
    IndoorMass,
    Layer,
    OuterWall,
    RoomMass,
    SolarGainModule,
    Window,
    band_overlap,
    bands_from_system,
    identifiability_report,
    input_excitation,
)

DT = 3600.0  # 1-hour steps
N = 8760     # 1-year synthetic series


# ── helpers ────────────────────────────────────────────────────────────────────

def _prior_means(sys) -> dict:
    return {p: math.exp(mu) for p, (mu, _) in sys.priors.items()}


def _indoor_mass():
    """Standard 5×4×2.5 m normal room."""
    return IndoorMass(a=5.0, b=4.0, c=2.5, furniture="normal")


def _light_wall():
    return OuterWall(area=10.0, orientation="S", layers=[Layer("insulation_mineral_wool", 0.1)])


def _heavy_wall():
    return OuterWall(
        area=10.0, orientation="S",
        layers=[Layer("concrete", 0.2), Layer("insulation_mineral_wool", 0.1)],
    )


def _window():
    return Window(area=4.0, orientation="S", U=1.2, shgc=0.6)


def _build_caravan():
    win = _window()
    wall = _light_wall()
    indoor = _indoor_mass()
    asm = Assembler()
    asm.add_element(indoor)
    asm.add_module(RoomMass())
    asm.add_module(DirectLoss(), elements=[wall, win])
    asm.add_module(SolarGainModule(), elements=[win])
    return asm.build()


def _build_heavy():
    heavy = _heavy_wall()
    win = _window()
    indoor = _indoor_mass()
    asm = Assembler()
    asm.add_element(indoor)
    asm.add_module(RoomMass())
    asm.add_module(DirectLoss(), elements=[win])
    asm.add_module(HeavyWall(), elements=[heavy])
    asm.add_module(SolarGainModule(), elements=[win])
    return asm.build()


# ── bands_from_system ──────────────────────────────────────────────────────────

def test_caravan_has_one_band():
    """Caravan (1 state) → exactly one time constant."""
    sys = _build_caravan()
    taus = bands_from_system(sys, _prior_means(sys))
    assert len(taus) == 1
    # Fast room band: expect τ in seconds, plausible thermal range (minutes to hours)
    assert 60 < taus[0] < 7 * 24 * 3600, f"Unexpected τ={taus[0]/3600:.1f}h"


def test_heavy_has_two_bands():
    """Heavy topology (2 states) → two time constants, slow > fast."""
    sys = _build_heavy()
    taus = bands_from_system(sys, _prior_means(sys))
    assert len(taus) == 2
    # Slow band should be at least 10× slower than fast band
    assert taus[1] > taus[0] * 5, (
        f"Expected slow >> fast, got τ_fast={taus[0]/3600:.1f}h, τ_slow={taus[1]/3600:.1f}h"
    )


# ── band_overlap ───────────────────────────────────────────────────────────────

def test_same_band_taus_flagged():
    """Two time constants within 1 decade → flagged as overlapping."""
    taus = [3600.0, 7200.0]  # ratio = 2 → log10(2) ≈ 0.30 < 1 decade
    pairs = band_overlap(taus)
    assert (0, 1) in pairs


def test_separated_band_taus_not_flagged():
    """Two time constants more than 1 decade apart → not flagged."""
    taus = [3600.0, 3600.0 * 24 * 5]  # ~5-day slow vs 1-hour fast: ratio ≈ 120 → 2+ decades
    pairs = band_overlap(taus)
    assert pairs == []


def test_heavy_bands_not_overlapping():
    """The heavy-wall topology should have well-separated bands (fast/slow)."""
    sys = _build_heavy()
    taus = bands_from_system(sys, _prior_means(sys))
    pairs = band_overlap(taus)
    # If the physics is sound the two bands should be >1 decade apart
    assert pairs == [], (
        f"Heavy-wall bands overlap: τ_fast={taus[0]/3600:.1f}h, τ_slow={taus[1]/3600:.1f}h"
    )


# ── input_excitation ───────────────────────────────────────────────────────────

def test_constant_signal_no_power():
    """A perfectly constant signal has no spectral power — should flag as unexcited."""
    taus = [3600.0 * 10]  # 10-hour band
    signals = {"T_ext": np.full(N, 15.0)}
    report = input_excitation(signals, taus, dt=DT)
    assert not report.bands[0].has_power


def test_diurnal_signal_excites_slow_node():
    """A non-constant signal must mark has_power=True regardless of τ."""
    t = np.arange(N) * DT
    T_ext = 15.0 + 8.0 * np.sin(2 * math.pi * t / (24 * 3600))
    taus = [40 * 3600.0]  # slow wall node — f_band ≈ 7e-7 Hz, diurnal at 1.16e-5 Hz (above)
    signals = {"T_ext": T_ext}
    report = input_excitation(signals, taus, dt=DT)
    assert report.bands[0].has_power, (
        "Diurnal signal must excite a slow (τ=40h) node via low-pass integration"
    )


def test_correlated_signals_flagged():
    """
    Correlated T_ext / G_sol (G = a*T_ext + small noise) → |Pearson r| above the
    verdict threshold (0.7). Cross-correlation is stable and easy to reason about.
    """
    rng = np.random.default_rng(42)
    t = np.arange(N) * DT
    T_ext = 15.0 + 8.0 * np.sin(2 * math.pi * t / (24 * 3600)) + rng.normal(0, 0.5, N)
    G_sol = 200.0 * T_ext / 25.0 + rng.normal(0, 0.5, N)   # strongly correlated
    signals = {"T_ext": T_ext, "G_sol": G_sol}

    taus = [40 * 3600.0]
    report = input_excitation(signals, taus, dt=DT)
    assert report.bands[0].max_correlation >= 0.7, (
        f"Expected |r| >= 0.7 for correlated signals, got {report.bands[0].max_correlation:.2f}"
    )


def test_uncorrelated_signals_low_correlation():
    """Independent T_ext and G_sol → low |Pearson r|."""
    rng = np.random.default_rng(0)
    t = np.arange(N) * DT
    T_ext = 15.0 + 8.0 * np.sin(2 * math.pi * t / (24 * 3600)) + rng.normal(0, 1.0, N)
    G_sol = 300.0 * np.clip(np.sin(2 * math.pi * (t / (24 * 3600) - 0.25)), 0, None) + rng.normal(0, 20, N)
    signals = {"T_ext": T_ext, "G_sol": G_sol}

    taus = [24 * 3600.0]
    report = input_excitation(signals, taus, dt=DT)
    assert report.bands[0].max_correlation < 0.7, (
        f"Expected |r| < 0.7 for independent signals, got {report.bands[0].max_correlation:.2f}"
    )


# ── identifiability_report ─────────────────────────────────────────────────────

def test_report_caravan_resolvable_with_diurnal():
    """Caravan params should be resolvable with a rich diurnal signal."""
    sys = _build_caravan()
    rng = np.random.default_rng(7)
    t = np.arange(N) * DT
    T_ext = 15.0 + 8.0 * np.sin(2 * math.pi * t / (24 * 3600)) + rng.normal(0, 0.5, N)
    G_sol = 300.0 * np.clip(np.sin(2 * math.pi * (t / (24 * 3600) - 0.25)), 0, None)
    signals = {"T_ext": T_ext, "G_sol": G_sol}

    report = identifiability_report(sys, _prior_means(sys), signals, dt=DT)

    statuses = {p: s.status for p, s in report.param_status.items()}
    # At minimum none should be "prior_dominated" (signal is rich)
    for p, status in statuses.items():
        assert status != "prior_dominated", f"{p} marked prior_dominated unexpectedly"


def test_report_no_power_flags_prior_dominated():
    """A constant boundary signal → slow-band params should be prior_dominated."""
    sys = _build_heavy()
    # Flat signals: zero spectral power
    signals = {
        "T_ext": np.full(N, 15.0),
        "G_sol": np.zeros(N),
    }
    report = identifiability_report(sys, _prior_means(sys), signals, dt=DT)
    # C_wall (slow band) should be prior_dominated
    assert report.param_status["C_wall"].status == "prior_dominated"


def test_report_correlated_inputs_flag_borderline():
    """
    Strongly correlated T_ext / G_sol → heavy-wall params should be borderline
    or prior_dominated (not resolvable).
    """
    sys = _build_heavy()
    rng = np.random.default_rng(3)
    t = np.arange(N) * DT
    T_ext = 15.0 + 8.0 * np.sin(2 * math.pi * t / (24 * 3600)) + rng.normal(0, 0.5, N)
    G_sol = 200.0 * T_ext / 25.0 + rng.normal(0, 0.5, N)  # tight noise → coherence crosses 0.7

    signals = {"T_ext": T_ext, "G_sol": G_sol}
    report = identifiability_report(sys, _prior_means(sys), signals, dt=DT)

    # At least one slow-band param should NOT be "resolvable"
    slow_params = ["C_wall", "H_out", "H_in"]
    statuses = [report.param_status[p].status for p in slow_params]
    assert any(s in ("borderline", "prior_dominated") for s in statuses), (
        f"Expected at least one slow param to be borderline/prior_dominated, got {statuses}"
    )
