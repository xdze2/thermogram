"""
Thermal Room Estimator — Streamlit UI

Phase 1: room description → RC model priors display.
"""

import streamlit as st

from thermal.models import Room, EnvelopeElement, MaterialLayer, ElementType, Orientation
from thermal.materials_db import MATERIALS
from thermal.priors import build_priors, ParameterPrior

st.set_page_config(page_title="Thermal Room Estimator", layout="wide")

# ── helpers ───────────────────────────────────────────────────────────────────

MATERIAL_OPTIONS = {v.name: k for k, v in MATERIALS.items()}
MATERIAL_NAMES   = list(MATERIAL_OPTIONS.keys())
ORIENT_LABELS    = [o.value for o in Orientation]
ELEMENT_TYPE_LABELS = [e.value for e in ElementType]


def material_key(name: str) -> str:
    return MATERIAL_OPTIONS[name]


# ── session state ─────────────────────────────────────────────────────────────

if "elements" not in st.session_state:
    st.session_state.elements = []


# ── sidebar: room description ─────────────────────────────────────────────────

with st.sidebar:
    st.title("Room description")

    st.subheader("Location")
    lat = st.number_input("Latitude (°N)",  value=48.85, min_value=-90.0,  max_value=90.0,  step=0.1)
    lon = st.number_input("Longitude (°E)", value=2.35,  min_value=-180.0, max_value=180.0, step=0.1)

    st.subheader("Geometry")
    room_name  = st.text_input("Room name", value="Living room")
    floor_area = st.number_input("Floor area (m²)", value=25.0, min_value=1.0)
    height     = st.number_input("Ceiling height (m)", value=2.5, min_value=1.5, max_value=10.0, step=0.1)

    st.subheader("Ventilation & gains")
    ach   = st.number_input("Air changes per hour (ACH)", value=0.5, min_value=0.1, step=0.1)
    q_int = st.number_input("Internal gains (W)", value=200, step=50)


# ── main ──────────────────────────────────────────────────────────────────────

st.title("Thermal Room Estimator")
st.caption("2R2C RC model · Gaussian priors from room description · ready for Bayesian fit")

col_left, col_right = st.columns([1, 2])

# ── left: envelope editor ─────────────────────────────────────────────────────

with col_left:
    st.subheader("Envelope elements")

    with st.form("add_element", clear_on_submit=True):
        el_name   = st.text_input("Name", value="South wall")
        el_type   = st.selectbox("Type", ELEMENT_TYPE_LABELS)
        el_orient = st.selectbox("Orientation", ORIENT_LABELS,
                                 index=ORIENT_LABELS.index("S"))
        el_area   = st.number_input("Area (m²)", value=10.0, min_value=0.1)

        if el_type == "window":
            el_u_override = st.number_input("U-value (W/m²·K)", value=1.4, min_value=0.1)
            el_shgc = st.number_input("SHGC", value=0.6, min_value=0.0, max_value=1.0, step=0.05)
            layers_data = []
        else:
            el_u_override = 0.0
            el_shgc = 0.6
            st.markdown("**Material layers** (inside → outside)")
            n_layers = st.number_input("Number of layers", value=2, min_value=1, max_value=8)
            layers_data = []
            for i in range(int(n_layers)):
                c1, c2 = st.columns(2)
                mat_name  = c1.selectbox(f"Layer {i+1}", MATERIAL_NAMES, key=f"mat_{i}")
                thickness = c2.number_input("mm", value=100, min_value=1, key=f"th_{i}")
                layers_data.append((mat_name, thickness / 1000.0))

        is_ground = st.checkbox("Ground contact (floor/basement)")

        if st.form_submit_button("Add element", type="primary"):
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

    # Quick presets
    st.subheader("Quick presets")
    c1, c2 = st.columns(2)

    def _add(elem: EnvelopeElement):
        st.session_state.elements.append(elem)

    if c1.button("Brick wall 30cm"):
        _add(EnvelopeElement("Brick wall", ElementType.WALL, Orientation.S, 10.0,
            [MaterialLayer("gypsum_board", 0.013),
             MaterialLayer("brick_common", 0.30),
             MaterialLayer("cement_plaster", 0.015)]))

    if c2.button("Insulated wall"):
        _add(EnvelopeElement("Insulated wall", ElementType.WALL, Orientation.W, 8.0,
            [MaterialLayer("gypsum_board", 0.013),
             MaterialLayer("mineral_wool", 0.14),
             MaterialLayer("brick_common", 0.15),
             MaterialLayer("cement_plaster", 0.015)]))

    if c1.button("Double-pane window"):
        _add(EnvelopeElement("Window", ElementType.WINDOW, Orientation.S, 2.0,
            [], u_value_override=1.4, shgc=0.6))

    if c2.button("Flat roof (insulated)"):
        _add(EnvelopeElement("Flat roof", ElementType.ROOF, Orientation.HORIZONTAL, 25.0,
            [MaterialLayer("gypsum_board", 0.013),
             MaterialLayer("mineral_wool", 0.20),
             MaterialLayer("concrete_dense", 0.15),
             MaterialLayer("bitumen_membrane", 0.005)]))

    # Elements list
    if st.session_state.elements:
        st.divider()
        for i, elem in enumerate(st.session_state.elements):
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"**{elem.name}** — {elem.type.value} — {elem.area} m²")
            if c2.button("✕", key=f"del_{i}"):
                st.session_state.elements.pop(i)
                st.rerun()

        if st.button("Clear all", type="secondary"):
            st.session_state.elements = []
            st.rerun()


# ── right: RC model priors ────────────────────────────────────────────────────

with col_right:
    if not st.session_state.elements:
        st.info("Add envelope elements on the left to see the RC model priors.")
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
    )

    st.subheader("RC model priors")
    st.caption(
        "2R2C + sol-air model. Five parameters with Gaussian priors derived from "
        "the room description. These become the starting point for the Bayesian fit."
    )

    priors = build_priors(room)

    _C_SCALE = 1e6  # J/K → MJ/K

    def _render_prior(p: ParameterPrior):
        scale      = _C_SCALE if p.unit == "MJ/K" else 1.0
        mu_disp    = p.mu    / scale
        sigma_disp = p.sigma / scale
        cv         = p.sigma / p.mu * 100 if p.mu > 0 else 0.0

        col_head, col_kpi = st.columns([3, 1])
        with col_head:
            st.markdown(f"**{p.symbol} — {p.name}**  `{mu_disp:.3g} ± {sigma_disp:.2g} {p.unit}`")
            st.caption(f"{p.description}  |  CV = {cv:.0f}%")
        with col_kpi:
            st.metric(label=p.symbol, value=f"{mu_disp:.3g} {p.unit}",
                      delta=f"±{sigma_disp:.2g} ({cv:.0f}%)", delta_color="off")

        lines = []
        for c in p.contributions:
            c_disp   = c.value / scale
            sig_disp = c.sigma / scale
            bar_n    = int(round(c.value / p.mu * 20)) if p.mu > 0 else 0
            bar      = "█" * bar_n + "░" * (20 - bar_n)
            lines.append(
                f"  + {c_disp:>8.3g} {p.unit}  ±{sig_disp:.2g}  │{bar}│  {c.label}"
                + (f"\n               {c.detail}" if c.detail else "")
            )
        lines.append(f"  {'─'*10}")
        lines.append(f"  = {mu_disp:>8.3g} {p.unit}  ±{sigma_disp:.2g}  (quadrature)")
        st.code("\n".join(lines), language=None)

    tabs = st.tabs([p.symbol for p in priors.values()])
    for tab, p in zip(tabs, priors.values()):
        with tab:
            _render_prior(p)
