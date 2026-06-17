"""
Thermal Room Estimator — Streamlit UI
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

from thermal.models import Room, EnvelopeElement, MaterialLayer, ElementType, Orientation
from thermal.materials_db import MATERIALS
from thermal.iso6946 import element_u_value, ua_total, element_summary
from thermal.weather import fetch_weather, weather_stats
from thermal.rc_simulation import (
    run_simulation, annual_summary,
    total_loss_coeff, ventilation_loss_coeff, effective_capacitance,
)
from thermal.priors import build_priors, ParameterPrior

st.set_page_config(page_title="Thermal Room Estimator", layout="wide")

# ── helpers ──────────────────────────────────────────────────────────────────

MATERIAL_OPTIONS = {v.name: k for k, v in MATERIALS.items()}
MATERIAL_NAMES   = list(MATERIAL_OPTIONS.keys())

ORIENT_LABELS = [o.value for o in Orientation]
ELEMENT_TYPE_LABELS = [e.value for e in ElementType]

KAPPA_PRESETS = {
    "Very light (timber frame, plasterboard)": 40,
    "Light (light concrete, few partitions)":  70,
    "Medium (concrete, brick partitions)":    110,
    "Heavy (solid concrete / stone)":         165,
}


def material_key(name: str) -> str:
    return MATERIAL_OPTIONS[name]


# ── session state: list of elements ──────────────────────────────────────────

if "elements" not in st.session_state:
    st.session_state.elements = []

if "weather_cache" not in st.session_state:
    st.session_state.weather_cache = {}


# ── sidebar: room + location ──────────────────────────────────────────────────

with st.sidebar:
    st.title("Room description")

    st.subheader("Location")
    lat = st.number_input("Latitude (°N)",  value=48.85, min_value=-90.0, max_value=90.0,  step=0.1)
    lon = st.number_input("Longitude (°E)", value=2.35,  min_value=-180.0, max_value=180.0, step=0.1)
    year = st.number_input("Reference year (historical)", value=2023, min_value=1940, max_value=2024, step=1)

    st.subheader("Room geometry")
    room_name    = st.text_input("Room name", value="Living room")
    floor_area   = st.number_input("Floor area (m²)", value=25.0, min_value=1.0)
    height       = st.number_input("Ceiling height (m)", value=2.5, min_value=1.5, max_value=10.0, step=0.1)

    st.subheader("Internal conditions")
    t_heat = st.number_input("Heating setpoint (°C)", value=20.0)
    t_cool = st.number_input("Cooling setpoint (°C)", value=26.0)
    ach    = st.number_input("Air changes per hour (ACH)", value=0.5, min_value=0.1, step=0.1)
    q_int  = st.number_input("Internal gains (W)", value=200, step=50)
    kappa_label = st.selectbox("Thermal mass class", list(KAPPA_PRESETS.keys()), index=1)
    kappa = KAPPA_PRESETS[kappa_label]


# ── main: add envelope elements ───────────────────────────────────────────────

st.title("Thermal Room Estimator")
st.caption("ISO 6946 U-values · ISO 52016 RC simulation · Open-Meteo weather")

col_left, col_right = st.columns([1, 2])

with col_left:
    st.subheader("Add envelope element")

    with st.form("add_element", clear_on_submit=True):
        el_name   = st.text_input("Name", value="South wall")
        el_type   = st.selectbox("Type", ELEMENT_TYPE_LABELS)
        el_orient = st.selectbox("Orientation", ORIENT_LABELS,
                                 index=ORIENT_LABELS.index("S"))
        el_area   = st.number_input("Area (m²)", value=10.0, min_value=0.1)

        if el_type == "window":
            el_u_override = st.number_input(
                "U-value override (W/m²·K) — leave 0 to compute from layers",
                value=1.4, min_value=0.0)
            el_shgc = st.number_input("SHGC (solar heat gain coeff.)", value=0.6,
                                       min_value=0.0, max_value=1.0, step=0.05)
            layers_data = []
        else:
            el_u_override = 0.0
            el_shgc = 0.6
            st.markdown("**Material layers** (inside → outside)")
            n_layers = st.number_input("Number of layers", value=2, min_value=1, max_value=8)
            layers_data = []
            for i in range(int(n_layers)):
                c1, c2 = st.columns(2)
                mat_name  = c1.selectbox(f"Layer {i+1} material", MATERIAL_NAMES,
                                          key=f"mat_{i}")
                thickness = c2.number_input(f"Thickness (mm)", value=100, min_value=1,
                                             key=f"th_{i}")
                layers_data.append((mat_name, thickness / 1000.0))

        is_ground = st.checkbox("Ground contact (floor/basement)")

        submitted = st.form_submit_button("Add element", type="primary")
        if submitted:
            layers = [MaterialLayer(material_key(m), t) for m, t in layers_data]
            elem = EnvelopeElement(
                name=el_name,
                type=ElementType(el_type),
                orientation=Orientation(el_orient),
                area=el_area,
                layers=layers,
                u_value_override=el_u_override if el_u_override > 0 else None,
                shgc=el_shgc,
                is_ground_contact=is_ground,
            )
            st.session_state.elements.append(elem)
            st.success(f"Added: {el_name}")

    # Quick-add presets
    st.subheader("Quick presets")
    presets_col1, presets_col2 = st.columns(2)

    def add_preset(elem: EnvelopeElement):
        st.session_state.elements.append(elem)

    if presets_col1.button("Brick wall 30cm"):
        add_preset(EnvelopeElement("Brick wall", ElementType.WALL, Orientation.S, 10.0,
            [MaterialLayer("gypsum_board", 0.013),
             MaterialLayer("brick_common", 0.30),
             MaterialLayer("cement_plaster", 0.015)]))

    if presets_col2.button("Insulated wall"):
        add_preset(EnvelopeElement("Insulated wall", ElementType.WALL, Orientation.W, 8.0,
            [MaterialLayer("gypsum_board", 0.013),
             MaterialLayer("mineral_wool", 0.14),
             MaterialLayer("brick_common", 0.15),
             MaterialLayer("cement_plaster", 0.015)]))

    if presets_col1.button("Double-pane window"):
        add_preset(EnvelopeElement("Window", ElementType.WINDOW, Orientation.S, 2.0,
            [], u_value_override=1.4, shgc=0.6))

    if presets_col2.button("Flat roof (insulated)"):
        add_preset(EnvelopeElement("Flat roof", ElementType.ROOF, Orientation.HORIZONTAL, 25.0,
            [MaterialLayer("gypsum_board", 0.013),
             MaterialLayer("mineral_wool", 0.20),
             MaterialLayer("concrete_dense", 0.15),
             MaterialLayer("bitumen_membrane", 0.005)]))

    # Current elements list
    if st.session_state.elements:
        st.subheader("Elements")
        for i, elem in enumerate(st.session_state.elements):
            u = element_u_value(elem)
            c1, c2 = st.columns([3, 1])
            c1.markdown(f"**{elem.name}** — {elem.area} m² — U={u:.2f} W/m²·K")
            if c2.button("✕", key=f"del_{i}"):
                st.session_state.elements.pop(i)
                st.rerun()

        if st.button("Clear all elements", type="secondary"):
            st.session_state.elements = []
            st.rerun()


# ── right column: results ─────────────────────────────────────────────────────

with col_right:
    if not st.session_state.elements:
        st.info("Add envelope elements on the left to start.")
        st.stop()

    room = Room(
        name=room_name,
        floor_area=floor_area,
        height=height,
        latitude=lat,
        longitude=lon,
        elements=st.session_state.elements,
        internal_gains_w=q_int,
        ach=ach,
        kappa=kappa,
        t_set_heating=t_heat,
        t_set_cooling=t_cool,
    )

    # ── Static analysis ───────────────────────────────────────────────────────
    st.subheader("Static analysis (ISO 6946)")

    summaries = [element_summary(e) for e in room.elements]
    df_elem = pd.DataFrame([{
        "Element":       s["name"],
        "Type":          s["type"],
        "Orient.":       s["orientation"],
        "Area (m²)":     s["area_m2"],
        "U (W/m²·K)":   s["U_value"],
        "R_total (m²·K/W)": s["R_total"],
        "UA (W/K)":      s["UA"],
        "κ (kJ/m²·K)":  s["thermal_mass_kJ_m2K"],
    } for s in summaries])

    st.dataframe(df_elem, use_container_width=True, hide_index=True)

    ua  = ua_total(room.elements)
    hve = ventilation_loss_coeff(room)
    H   = total_loss_coeff(room)
    C   = effective_capacitance(room)
    tau = C / (H * 3600)  # time constant in hours

    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
    kpi1.metric("UA envelope", f"{ua:.1f} W/K")
    kpi2.metric("H_vent", f"{hve:.1f} W/K")
    kpi3.metric("H_total", f"{H:.1f} W/K")
    kpi4.metric("Time constant τ", f"{tau:.1f} h")
    kpi5.metric("Thermal mass C", f"{C/1e6:.2f} MJ/K")

    # UA breakdown pie
    ua_vals = [element_u_value(e) * e.area for e in room.elements]
    ua_names = [e.name for e in room.elements]
    ua_names.append("Ventilation")
    ua_vals.append(hve)

    fig_ua = px.pie(values=ua_vals, names=ua_names,
                    title="Heat loss breakdown (UA)",
                    hole=0.4)
    fig_ua.update_layout(margin=dict(t=40, b=0, l=0, r=0), height=300)
    st.plotly_chart(fig_ua, use_container_width=True)

    # ── RC model priors ───────────────────────────────────────────────────────
    st.subheader("RC model parameters & priors")
    st.caption(
        "2R2C + sol-air model: H_env, H_ve, C_wall, C_room, α_eff. "
        "Priors are derived from the element descriptions above. "
        "σ combines uncertainties in quadrature across elements."
    )

    priors = build_priors(room)

    # Display scale factors for C parameters
    _C_SCALE = 1e6   # J/K → MJ/K

    def _render_prior(p: ParameterPrior):
        scale = _C_SCALE if p.unit == "MJ/K" else 1.0
        mu_disp    = p.mu    / scale
        sigma_disp = p.sigma / scale
        cv = p.sigma / p.mu * 100 if p.mu > 0 else 0

        col_head, col_kpi = st.columns([3, 1])
        with col_head:
            st.markdown(f"**{p.symbol} — {p.name}**  `{mu_disp:.3g} ± {sigma_disp:.2g} {p.unit}`")
            st.caption(f"{p.description}  |  CV = {cv:.0f}%")
        with col_kpi:
            st.metric(label=p.symbol, value=f"{mu_disp:.3g} {p.unit}",
                      delta=f"±{sigma_disp:.2g} ({cv:.0f}%)",
                      delta_color="off")

        # Contribution breakdown
        lines = []
        for c in p.contributions:
            c_disp     = c.value / scale
            sig_disp   = c.sigma / scale
            bar_filled = int(round(c.value / p.mu * 20)) if p.mu > 0 else 0
            bar        = "█" * bar_filled + "░" * (20 - bar_filled)
            lines.append(
                f"  + {c_disp:>8.3g} {p.unit}  ±{sig_disp:.2g}  │{bar}│  {c.label}"
                + (f"\n               {c.detail}" if c.detail else "")
            )
        lines.append(f"  {'─'*10}")
        lines.append(f"  = {mu_disp:>8.3g} {p.unit}  ±{sigma_disp:.2g}  (total, quadrature)")

        st.code("\n".join(lines), language=None)

    tabs = st.tabs([f"{p.symbol}" for p in priors.values()])
    for tab, p in zip(tabs, priors.values()):
        with tab:
            _render_prior(p)

    # ── Dynamic simulation ────────────────────────────────────────────────────
    st.subheader("Dynamic simulation (ISO 52016 RC model)")

    cache_key = (round(lat, 2), round(lon, 2), int(year))
    if cache_key not in st.session_state.weather_cache:
        with st.spinner(f"Fetching weather data for ({lat:.2f}, {lon:.2f}) …"):
            try:
                df_wx = fetch_weather(lat, lon, int(year))
                st.session_state.weather_cache[cache_key] = df_wx
            except Exception as e:
                st.error(f"Weather fetch failed: {e}")
                st.stop()
    df_wx = st.session_state.weather_cache[cache_key]

    wx = weather_stats(df_wx)
    wc1, wc2, wc3, wc4, wc5 = st.columns(5)
    wc1.metric("T_min", f"{wx['t_min']} °C")
    wc2.metric("T_max", f"{wx['t_max']} °C")
    wc3.metric("T_mean", f"{wx['t_mean']} °C")
    wc4.metric("HDD₁₈", f"{int(wx['HDD_18'])} °C·day")
    wc5.metric("Solar GHI", f"{int(wx['ghi_annual_kWh_m2'])} kWh/m²")

    with st.spinner("Running hourly simulation …"):
        sim = run_simulation(room, df_wx)

    summary = annual_summary(sim, room)

    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("Heating", f"{summary['E_heating_kWh']:.0f} kWh/yr",
               f"{summary['E_heating_kWh_m2']} kWh/m²")
    sc2.metric("Cooling", f"{summary['E_cooling_kWh']:.0f} kWh/yr",
               f"{summary['E_cooling_kWh_m2']} kWh/m²")
    sc3.metric("Peak heating", f"{summary['peak_heating_W']:.0f} W")
    sc4.metric("Peak cooling", f"{summary['peak_cooling_W']:.0f} W")

    # Energy balance Sankey / bar
    balance_labels = ["Solar gains", "Internal gains", "Heating input",
                      "Cond. losses", "Vent. losses", "Cooling removed"]
    balance_vals   = [
        summary["solar_gains_kWh"],
        summary["internal_gains_kWh"],
        summary["E_heating_kWh"],
        summary["cond_losses_kWh"],
        summary["vent_losses_kWh"],
        summary["E_cooling_kWh"],
    ]
    colors = ["#f0a500", "#e06c75", "#61afef",
              "#5c6370", "#abb2bf", "#56b6c2"]
    fig_bal = go.Figure(go.Bar(
        x=balance_labels, y=balance_vals,
        marker_color=colors, text=[f"{v:.0f}" for v in balance_vals],
        textposition="outside",
    ))
    fig_bal.update_layout(title="Annual energy balance (kWh)",
                          yaxis_title="kWh/year", height=320,
                          margin=dict(t=40, b=40))
    st.plotly_chart(fig_bal, use_container_width=True)

    # Monthly temperature + heating/cooling chart
    sim["month"] = sim.index.month
    monthly = sim.groupby("month").agg(
        t_in_mean=("t_in", "mean"),
        t_out_mean=("t_out", "mean"),
        q_heating=("q_heating", "sum"),
        q_cooling=("q_cooling", "sum"),
    ).reset_index()
    monthly["q_heating_kWh"] = monthly["q_heating"] / 1000
    monthly["q_cooling_kWh"] = monthly["q_cooling"] / 1000

    MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun",
                   "Jul","Aug","Sep","Oct","Nov","Dec"]
    monthly["month_name"] = [MONTH_NAMES[m-1] for m in monthly["month"]]

    fig_monthly = make_subplots(specs=[[{"secondary_y": True}]])
    fig_monthly.add_trace(go.Bar(
        x=monthly["month_name"], y=monthly["q_heating_kWh"],
        name="Heating (kWh)", marker_color="#61afef"), secondary_y=False)
    fig_monthly.add_trace(go.Bar(
        x=monthly["month_name"], y=monthly["q_cooling_kWh"],
        name="Cooling (kWh)", marker_color="#56b6c2"), secondary_y=False)
    fig_monthly.add_trace(go.Scatter(
        x=monthly["month_name"], y=monthly["t_in_mean"],
        name="T_in mean (°C)", mode="lines+markers",
        line=dict(color="#e06c75", width=2)), secondary_y=True)
    fig_monthly.add_trace(go.Scatter(
        x=monthly["month_name"], y=monthly["t_out_mean"],
        name="T_out mean (°C)", mode="lines+markers",
        line=dict(color="#abb2bf", width=2, dash="dot")), secondary_y=True)

    fig_monthly.update_layout(
        title="Monthly energy demand & temperatures",
        barmode="group", height=360,
        margin=dict(t=40, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig_monthly.update_yaxes(title_text="Energy (kWh)", secondary_y=False)
    fig_monthly.update_yaxes(title_text="Temperature (°C)", secondary_y=True)
    st.plotly_chart(fig_monthly, use_container_width=True)

    # Week-detail selector
    st.subheader("Week detail")
    week_options = {
        "Winter (week 2, Jan)": ("2023-01-09", "2023-01-15"),
        "Spring  (week 14, Apr)": ("2023-04-03", "2023-04-09"),
        "Summer  (week 28, Jul)": ("2023-07-10", "2023-07-16"),
        "Autumn  (week 42, Oct)": ("2023-10-16", "2023-10-22"),
    }
    chosen_week = st.selectbox("Select week", list(week_options.keys()))
    w_start, w_end = week_options[chosen_week]
    sim_week = sim.loc[w_start:w_end]

    fig_week = make_subplots(specs=[[{"secondary_y": True}]])
    fig_week.add_trace(go.Scatter(
        x=sim_week.index, y=sim_week["t_in"],
        name="T indoor (°C)", line=dict(color="#e06c75")), secondary_y=True)
    fig_week.add_trace(go.Scatter(
        x=sim_week.index, y=sim_week["t_out"],
        name="T outdoor (°C)", line=dict(color="#abb2bf", dash="dot")), secondary_y=True)
    fig_week.add_trace(go.Bar(
        x=sim_week.index, y=sim_week["q_heating"] / 1000,
        name="Heating (kW)", marker_color="#61afef", opacity=0.6), secondary_y=False)
    fig_week.add_trace(go.Bar(
        x=sim_week.index, y=sim_week["q_cooling"] / 1000,
        name="Cooling (kW)", marker_color="#56b6c2", opacity=0.6), secondary_y=False)
    fig_week.add_trace(go.Scatter(
        x=sim_week.index, y=sim_week["q_solar"] / 1000,
        name="Solar gains (kW)", line=dict(color="#f0a500", dash="dash")), secondary_y=False)

    fig_week.update_layout(
        title=f"Hourly detail — {chosen_week}",
        height=380, barmode="overlay",
        margin=dict(t=40, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig_week.update_yaxes(title_text="Power (kW)", secondary_y=False)
    fig_week.update_yaxes(title_text="Temperature (°C)", secondary_y=True)
    st.plotly_chart(fig_week, use_container_width=True)
