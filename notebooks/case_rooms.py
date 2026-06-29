"""
Case notebook — thnodes canonical rooms.

Run with:  uv run streamlit run notebooks/case_rooms.py

One tab per canonical room:
  • Caravan       — all-light, single fast band
  • Heavy-wall    — heavy envelope, two bands (diurnal excitation)
  • Collinear     — heavy-wall with correlated T_ext/G_sol → ridge posterior expected
  • Cellar        — ground-coupled, constant interior (simulation only, no solar)
"""

import math
import sys
from pathlib import Path

import numpy as np
import streamlit as st

# NOTE: Streamlit 1.58 + Python 3.12 prints "RuntimeError: Event loop is closed"
# on the first script teardown. This is a cosmetic bug in Streamlit's thread
# shutdown — the app renders correctly. No fix available at this version.

# Allow running from the repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from thnodes import (
    Assembler,
    Channel,
    DirectLoss,
    HeavyWall,
    Layer,
    OuterWall,
    RoomMass,
    SolarGainModule,
    Window,
    elements_table,
    forward_sim,
    identifiability_report,
    topology_svg,
)
from thnodes.identifiability import bands_from_system, band_overlap

# ── constants ──────────────────────────────────────────────────────────────────

DT = 3600.0        # 1-hour steps
N_HOURS = 7 * 24  # 1-week simulation
N_SIG = 8760      # 1-year synthetic signal for identifiability lens

STATUS_COLOR = {
    "resolvable": "🟢",
    "borderline": "🟡",
    "prior_dominated": "🔴",
}


# ── shared helpers ─────────────────────────────────────────────────────────────

def prior_means(sys_) -> dict:
    return {p: math.exp(mu) for p, (mu, _) in sys_.priors.items()}


def diurnal_signals(n: int, T_mean: float, T_amp: float, G_amp: float, correlated: bool) -> dict:
    """Synthetic diurnal T_ext + G_sol. correlated=True → G = a·T_ext + small noise."""
    t = np.arange(n) * DT
    rng = np.random.default_rng(0)
    T_ext = T_mean + T_amp * np.sin(2 * math.pi * t / (24 * 3600)) + rng.normal(0, 0.5, n)
    if correlated:
        G_sol = np.clip(300.0 * T_ext / (T_mean + T_amp) + rng.normal(0, 0.5, n), 0, None)
    else:
        G_sol = G_amp * np.clip(np.sin(2 * math.pi * (t / (24 * 3600) - 0.25)), 0, None)
        G_sol += rng.normal(0, 5.0, n)
    return {"T_ext": T_ext, "G_sol": G_sol}


def ground_signals(n: int, T_ground: float) -> dict:
    return {"T_ground": np.full(n, T_ground)}


# ── rendering helpers ──────────────────────────────────────────────────────────

def render_elements(elements):
    """Pre-assembly view: each element the user described, with computed budgets."""
    st.dataframe(elements_table(elements), width="stretch")


def render_topology(sys_):
    """Post-assembly view: the RC ladder schematic (schemdraw → SVG)."""
    st.image(topology_svg(sys_))


def render_ownership_table(sys_):
    """Render the (element × channel) → module routing table."""
    omap = sys_.ownership_map()
    if not omap:
        st.info("No element-channel cells routed (RoomMass only).")
        return

    elements = sorted({elem for elem, _ in omap})
    channels = sorted({ch for _, ch in omap}, key=lambda c: c.name)

    rows = []
    for elem in elements:
        row = {"Element": elem}
        for ch in channels:
            row[ch.name] = omap.get((elem, ch), "—")
        rows.append(row)

    st.dataframe(rows, width="stretch")


def render_bands(taus: list[float], overlapping: list[tuple[int, int]]):
    overlap_set = {i for pair in overlapping for i in pair}
    rows = []
    for k, tau in enumerate(taus):
        flag = "⚠️ overlap" if k in overlap_set else "✓"
        rows.append({"Band": k, "τ (hours)": f"{tau/3600:.1f}", "Status": flag})
    st.dataframe(rows, width="stretch")


def render_ident_report(report):
    rows = []
    for param, ps in sorted(report.param_status.items()):
        tau_str = f"{ps.tau_h:.1f} h" if ps.tau_h is not None else "—"
        corr_str = f"{ps.correlation:.2f}" if ps.correlation is not None else "—"
        rows.append({
            "Parameter": param,
            "Band τ": tau_str,
            "|r| T_ext/G_sol": corr_str,
            "Status": f"{STATUS_COLOR[ps.status]} {ps.status}",
            "Reason": ps.reason,
        })
    st.dataframe(rows, width="stretch")


def render_sim_plot(sys_, signals_sim: dict, x0: np.ndarray, label: str):
    import matplotlib.pyplot as plt

    params = prior_means(sys_)
    t_span = (0, N_HOURS * DT)
    t, x = forward_sim(sys_, signals_sim, t_span, x0, params, dt=DT)
    t_h = t / 3600

    fig, axes = plt.subplots(2, 1, figsize=(9, 4), sharex=True)

    # State trajectories
    for k, name in enumerate(sys_.state_names):
        axes[0].plot(t_h, x[k], label=name)
    axes[0].set_ylabel("Temperature (°C)")
    axes[0].legend(fontsize=8)
    axes[0].set_title(f"{label} — forward simulation (prior-mean params)")

    # Boundary signals (T_ext or T_ground, whichever is present)
    bnd_key = "T_ext" if "T_ext" in signals_sim else "T_ground"
    bnd_arr = signals_sim[bnd_key]
    axes[1].plot(t_h, bnd_arr[: len(t_h)], color="grey", lw=1, label=bnd_key)
    if "G_sol" in signals_sim:
        ax2 = axes[1].twinx()
        ax2.fill_between(t_h, signals_sim["G_sol"][: len(t_h)], alpha=0.25, color="orange")
        ax2.set_ylabel("G_sol (W/m²)", color="orange", fontsize=8)
        ax2.tick_params(axis="y", labelcolor="orange")
    axes[1].set_xlabel("Time (hours)")
    axes[1].set_ylabel("°C")
    axes[1].legend(fontsize=8)

    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)


# ── room builders ──────────────────────────────────────────────────────────────

def build_caravan():
    wall = OuterWall(area=12.0, orientation="S", layers=[Layer("insulation_mineral_wool", 0.05)])
    win  = Window(area=3.0, orientation="S", U=2.8, shgc=0.7)
    asm  = Assembler()
    asm.add_module(RoomMass(floor_area=15.0))
    asm.add_module(DirectLoss(), elements=[wall, win])
    asm.add_module(SolarGainModule(), elements=[win])
    return asm.build(), [wall, win]


def build_heavy():
    wall = OuterWall(
        area=20.0, orientation="S",
        layers=[Layer("concrete", 0.25), Layer("insulation_mineral_wool", 0.1)],
    )
    win  = Window(area=4.0, orientation="S", U=1.2, shgc=0.6)
    asm  = Assembler()
    asm.add_module(RoomMass(floor_area=20.0))
    asm.add_module(DirectLoss(), elements=[win])
    asm.add_module(HeavyWall(), elements=[wall])
    asm.add_module(SolarGainModule(), elements=[win])
    return asm.build(), [wall, win]


# ── tab renderers ──────────────────────────────────────────────────────────────

def tab_caravan():
    st.header("Caravan — all-light, single fast band")
    st.caption(
        "RoomMass + DirectLoss + SolarGain. No heavy mass → single T_room state. "
        "Fast time constant, identifiable under any diurnal excitation."
    )

    sys_, elements = build_caravan()

    st.subheader("Elements")
    render_elements(elements)

    st.subheader("Topology schematic")
    render_topology(sys_)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Topology routing")
        render_ownership_table(sys_)
        st.caption(f"States: {sys_.state_names} | Params: {sys_.param_names}")

    with col2:
        taus = bands_from_system(sys_, prior_means(sys_))
        overlapping = band_overlap(taus)
        st.subheader("Time-constant bands")
        render_bands(taus, overlapping)

    st.subheader("Forward simulation")
    sigs_sim = diurnal_signals(N_HOURS + 2, T_mean=10.0, T_amp=8.0, G_amp=400.0, correlated=False)
    render_sim_plot(sys_, sigs_sim, x0=np.array([10.0]), label="Caravan")

    st.subheader("Identifiability lens (1-year diurnal signals)")
    sigs_lens = diurnal_signals(N_SIG, T_mean=10.0, T_amp=8.0, G_amp=400.0, correlated=False)
    report = identifiability_report(sys_, prior_means(sys_), sigs_lens, dt=DT)
    render_ident_report(report)


def tab_heavy():
    st.header("Heavy-wall — two bands, good excitation")
    st.caption(
        "RoomMass + DirectLoss + HeavyWall + SolarGain. "
        "T_wall (slow) + T_room (fast). Independent diurnal signals → both bands identifiable."
    )

    sys_, elements = build_heavy()

    st.subheader("Elements")
    render_elements(elements)

    st.subheader("Topology schematic")
    render_topology(sys_)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Topology routing")
        render_ownership_table(sys_)
        st.caption(f"States: {sys_.state_names} | Params: {sys_.param_names}")

    with col2:
        taus = bands_from_system(sys_, prior_means(sys_))
        overlapping = band_overlap(taus)
        st.subheader("Time-constant bands")
        render_bands(taus, overlapping)

    st.subheader("Forward simulation")
    sigs_sim = diurnal_signals(N_HOURS + 2, T_mean=5.0, T_amp=12.0, G_amp=500.0, correlated=False)
    render_sim_plot(sys_, sigs_sim, x0=np.array([5.0, 5.0]), label="Heavy-wall")

    st.subheader("Identifiability lens (1-year diurnal, independent signals)")
    sigs_lens = diurnal_signals(N_SIG, T_mean=5.0, T_amp=12.0, G_amp=500.0, correlated=False)
    report = identifiability_report(sys_, prior_means(sys_), sigs_lens, dt=DT)
    render_ident_report(report)


def tab_collinear():
    st.header("Collinear — heavy-wall with correlated T_ext/G_sol")
    st.caption(
        "Same topology as Heavy-wall, but T_ext and G_sol are linearly correlated "
        "(as in passive diurnal data). The lens should flag slow-band params as borderline "
        "or prior_dominated — the same ridge Step 2's posterior will show."
    )

    sys_, elements = build_heavy()

    st.subheader("Elements")
    render_elements(elements)

    st.subheader("Topology schematic")
    render_topology(sys_)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Topology routing")
        render_ownership_table(sys_)
        st.caption(f"States: {sys_.state_names} | Params: {sys_.param_names}")

    with col2:
        taus = bands_from_system(sys_, prior_means(sys_))
        overlapping = band_overlap(taus)
        st.subheader("Time-constant bands")
        render_bands(taus, overlapping)

    st.subheader("Forward simulation (correlated signals)")
    sigs_sim = diurnal_signals(N_HOURS + 2, T_mean=5.0, T_amp=12.0, G_amp=500.0, correlated=True)
    render_sim_plot(sys_, sigs_sim, x0=np.array([5.0, 5.0]), label="Collinear heavy-wall")

    st.subheader("Identifiability lens (1-year correlated signals)")
    sigs_lens = diurnal_signals(N_SIG, T_mean=5.0, T_amp=12.0, G_amp=500.0, correlated=True)
    report = identifiability_report(sys_, prior_means(sys_), sigs_lens, dt=DT)
    render_ident_report(report)

    st.info(
        "🔍 Compare with the Heavy-wall tab: any params that flip from 🟢 resolvable "
        "to 🟡 borderline or 🔴 prior_dominated are exactly the parameters Step 2's "
        "posterior will show as a ridge."
    )


def tab_cellar():
    import warnings
    st.header("Cellar — ground-coupled, near-constant interior")
    st.caption(
        "RoomMass + DirectLoss (to T_ext, windows only). "
        "No solar, slow ground-driven dynamics. "
        "Simulation only — HeavySlab deferred until T_ground signal is available."
    )

    # Minimal cellar: just room + window conduction to T_ext, no solar.
    # SOLAR_TRANSMISSION on the window is intentionally unclaimed — suppress the warning.
    win = Window(area=1.0, orientation="N", U=2.0, shgc=0.1)
    asm = Assembler()
    asm.add_module(RoomMass(floor_area=25.0))
    asm.add_module(DirectLoss(), elements=[win])
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Unclaimed channel.*SOLAR_TRANSMISSION")
        sys_ = asm.build()

    st.subheader("Elements")
    render_elements([win])

    st.subheader("Topology schematic")
    render_topology(sys_)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Topology routing")
        render_ownership_table(sys_)
        st.caption(f"States: {sys_.state_names} | Params: {sys_.param_names}")
        st.warning(
            "HeavySlab deferred: T_ground not yet modelled. "
            "This is a stub — add HeavySlab once T_ground signal is available."
        )

    with col2:
        taus = bands_from_system(sys_, prior_means(sys_))
        overlapping = band_overlap(taus)
        st.subheader("Time-constant bands")
        render_bands(taus, overlapping)

    st.subheader("Forward simulation (slow seasonal T_ext swing)")
    # Slow seasonal signal: 180-day half-period, cellar barely moves
    t_sim = np.arange(N_HOURS + 2) * DT
    T_ext_cellar = 12.0 + 10.0 * np.sin(2 * math.pi * t_sim / (180 * 24 * 3600))
    sigs_sim = {"T_ext": T_ext_cellar, "G_sol": np.zeros(N_HOURS + 2)}
    render_sim_plot(sys_, sigs_sim, x0=np.array([14.0]), label="Cellar (stub)")

    st.subheader("Identifiability lens")
    sigs_lens = {"T_ext": T_ext_cellar[:N_SIG] if N_SIG <= len(T_ext_cellar) else
                 np.resize(T_ext_cellar, N_SIG),
                 "G_sol": np.zeros(N_SIG)}
    report = identifiability_report(sys_, prior_means(sys_), sigs_lens, dt=DT)
    render_ident_report(report)


# ── main ───────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="thnodes — case rooms", layout="wide")
st.title("thnodes — canonical room cases")
st.caption(
    "Validation artifact for Steps 0–1. "
    "Each tab: topology routing · time-constant bands · forward sim · identifiability lens."
)

tabs = st.tabs(["Caravan", "Heavy-wall", "Collinear", "Cellar (stub)"])
with tabs[0]:
    tab_caravan()
with tabs[1]:
    tab_heavy()
with tabs[2]:
    tab_collinear()
with tabs[3]:
    tab_cellar()
