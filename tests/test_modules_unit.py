"""
Stage 2b unit tests — each module / channel verified in isolation, before the
assembler wires them together. Ground truth is hand-computed per single element, so a
failure here points at a module's math, not at routing.
"""

import math

import pytest

from thermal.api_models import WallElement, WindowElement, FloorElement
from thermal.channels import (
    element_channels,
    heavy_layer_mass,
    CONDUCTION_EXT,
    SOLAR_SOLAIR,
    SOLAR_TRANSMITTED,
    STORAGE,
)
from thermal import modules as M


def _wall(**kw):
    kw.setdefault("orientation", "S")
    kw.setdefault("area_m2", 10.0)
    kw.setdefault("layers", [
        {"material_key": "brick_common", "thickness_m": 0.20},   # heavy
        {"material_key": "mineral_wool", "thickness_m": 0.10},   # light
    ])
    return WallElement(name="W", uid="w0000000", **kw)


def _light_wall():
    return WallElement(
        name="L", uid="l0000000", orientation="N", area_m2=8.0,
        layers=[{"material_key": "mineral_wool", "thickness_m": 0.12}],
    )


def _window():
    return WindowElement(name="Win", uid="win00000", orientation="S",
                         area_m2=2.0, u_value_override=1.4, shgc=0.6)


# --- channels.py ----------------------------------------------------------

def test_heavy_layer_mass_counts_only_heavy_layers():
    w = _wall()
    # brick_common rho=1800>500 ; mineral_wool rho=30 excluded
    expected = 1800 * 1000 * 0.20 * 10.0
    assert heavy_layer_mass(w) == pytest.approx(expected)


def test_channels_opaque_heavy():
    ch = element_channels(_wall())
    assert set(ch) == {CONDUCTION_EXT, SOLAR_SOLAIR, STORAGE}
    assert ch[SOLAR_SOLAIR].value == 10.0  # aperture area
    assert ch[STORAGE].value == pytest.approx(1800 * 1000 * 0.20 * 10.0)


def test_channels_light_opaque_has_no_storage():
    ch = element_channels(_light_wall())
    assert set(ch) == {CONDUCTION_EXT, SOLAR_SOLAIR}
    assert STORAGE not in ch


def test_channels_window():
    ch = element_channels(_window())
    assert set(ch) == {CONDUCTION_EXT, SOLAR_TRANSMITTED}
    assert ch[CONDUCTION_EXT].value == pytest.approx(1.4 * 2.0)


def test_channel_str_key():
    assert str(CONDUCTION_EXT) == "CONDUCTION@T_ext"
    assert str(STORAGE) == "STORAGE@—"


# --- RoomMass -------------------------------------------------------------

def test_room_mass_prior():
    [t] = M.RoomMass(floor_area_m2=40.0).derive_prior()
    assert t.param == "C_room"
    assert t.value == pytest.approx(20e3 * 40.0)
    assert t.sigma == pytest.approx(20e3 * 40.0 * 0.60)
    assert t.aggregation == "scalar"


# --- Ventilation ----------------------------------------------------------

def test_ventilation_prior():
    [t] = M.Ventilation(ach=0.5, volume=100.0).derive_prior()
    assert t.param == "H_ve"
    assert t.value == pytest.approx(0.34 * 0.5 * 100.0)
    assert t.sigma == pytest.approx(0.34 * 0.5 * 100.0 * 0.40)


# --- WindowLoss -----------------------------------------------------------

def test_window_loss_prior_and_claim():
    win = _window()
    mod = M.WindowLoss(win)
    assert mod.claims() == [(win, CONDUCTION_EXT)]
    [t] = mod.derive_prior()
    assert t.param == "H_ve"
    assert t.value == pytest.approx(1.4 * 2.0)
    assert t.sigma == pytest.approx(1.4 * 2.0 * 0.15)


# --- HeavyWall ------------------------------------------------------------

def _claim_keys(mod):
    return {(e.uid, ch) for e, ch in mod.claims()}


def test_heavy_wall_claims_all_three_when_heavy():
    w = _wall()
    mod = M.HeavyWall(w, element_channels(w))
    assert _claim_keys(mod) == {(w.uid, CONDUCTION_EXT), (w.uid, SOLAR_SOLAIR), (w.uid, STORAGE)}


def test_heavy_wall_light_omits_storage_claim():
    w = _light_wall()
    mod = M.HeavyWall(w, element_channels(w))
    assert _claim_keys(mod) == {(w.uid, CONDUCTION_EXT), (w.uid, SOLAR_SOLAIR)}


def test_heavy_wall_priors():
    w = _wall()
    terms = {t.param: t for t in M.HeavyWall(w, element_channels(w)).derive_prior()}
    assert set(terms) == {"H_env", "C_wall", "alpha_eff"}

    # H_env = U·A, σ=15%
    u = 1.0 / (0.13 + 0.04 + 0.20/0.6 + 0.10/0.035)
    assert terms["H_env"].value == pytest.approx(u * 10.0)
    assert terms["H_env"].sigma == pytest.approx(u * 10.0 * 0.15)

    # C_wall = brick heavy mass, σ=25%
    cw = 1800 * 1000 * 0.20 * 10.0
    assert terms["C_wall"].value == pytest.approx(cw)
    assert terms["C_wall"].sigma == pytest.approx(cw * 0.25)

    # alpha_eff: outer layer is mineral_wool → default (0.65, 0.15), area-weighted
    assert terms["alpha_eff"].value == pytest.approx(0.65)
    assert terms["alpha_eff"].sigma == pytest.approx(0.15)
    assert terms["alpha_eff"].aggregation == "area_weight"
    assert terms["alpha_eff"].weight == 10.0


def test_heavy_wall_alpha_uses_outer_layer_table():
    # outer layer cement_plaster → (0.60, 0.12)
    w = WallElement(name="W2", uid="w2000000", orientation="E", area_m2=5.0, layers=[
        {"material_key": "brick_common", "thickness_m": 0.20},
        {"material_key": "cement_plaster", "thickness_m": 0.02},
    ])
    terms = {t.param: t for t in M.HeavyWall(w, element_channels(w)).derive_prior()}
    assert terms["alpha_eff"].value == pytest.approx(0.60)
    assert terms["alpha_eff"].sigma == pytest.approx(0.12)


# --- SolarGain ------------------------------------------------------------

def test_solar_gain_claims_transmitted_no_prior():
    win = _window()
    mod = M.SolarGain(win)
    assert mod.claims() == [(win, SOLAR_TRANSMITTED)]
    assert mod.derive_prior() == []
