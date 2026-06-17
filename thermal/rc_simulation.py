"""
RC thermal network simulation — ISO 52016-1:2017 simplified 1-node model.

The room is modelled as a single thermal node (air + furniture mass) with:
  - conduction losses through envelope elements (U·A)
  - ventilation losses
  - solar gains through windows
  - internal gains
  - a lumped thermal mass (capacitance C)

Energy balance at each hourly timestep:
  C · dT/dt = Q_solar + Q_internal - UA_total·(T_in - T_out) - Q_vent ± Q_HVAC

HVAC is ideal (maintains setpoint when needed) so we output Q_HVAC demand.
"""

import numpy as np
import pandas as pd

from .models import Room, ElementType
from .iso6946 import element_u_value, ua_total
from .solar import solar_gains_series


def ventilation_loss_coeff(room: Room) -> float:
    """
    H_ve [W/K] — ventilation heat loss coefficient.
    H_ve = ρ·cp·n·V  with ρ·cp_air = 0.34 Wh/(m³·K) = 1224 J/(m³·K)
    """
    return 0.34 * room.ach * room.volume  # W/K  (0.34 Wh/(m³·K) × m³/h)


def total_loss_coeff(room: Room) -> float:
    """H_total [W/K] = UA_envelope + H_ve"""
    ua = ua_total(room.elements)
    hve = ventilation_loss_coeff(room)
    return ua + hve


def effective_capacitance(room: Room) -> float:
    """
    C_eff [J/K] — effective thermal capacitance of the zone.
    ISO 52016-1 uses κ [kJ/(m²·K)] × floor area.
    """
    return room.kappa * 1000 * room.floor_area  # J/K


def run_simulation(
    room: Room,
    weather_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Hourly RC simulation for one full year.

    Parameters
    ----------
    room       : Room description
    weather_df : hourly weather with t_out, ghi, dhi columns, UTC DatetimeIndex

    Returns
    -------
    DataFrame with columns:
      t_in, t_out, q_solar, q_internal, q_vent_loss, q_cond_loss,
      q_heating, q_cooling, q_net
    """
    dt = 3600.0  # seconds per timestep

    H_total = total_loss_coeff(room)
    H_ve    = ventilation_loss_coeff(room)
    ua_env  = ua_total(room.elements)
    C       = effective_capacitance(room)

    # Pre-compute solar gains for each window element
    q_solar_total = pd.Series(0.0, index=weather_df.index)
    for elem in room.elements:
        if elem.type == ElementType.WINDOW:
            gains = solar_gains_series(
                weather_df,
                room.latitude,
                room.longitude,
                elem.tilt,
                elem.orientation.value,
                elem.shgc,
                elem.area,
            )
            q_solar_total = q_solar_total + gains

    t_out_arr   = weather_df["t_out"].values
    q_solar_arr = q_solar_total.values
    n_steps     = len(t_out_arr)

    t_in_arr     = np.zeros(n_steps)
    q_heat_arr   = np.zeros(n_steps)
    q_cool_arr   = np.zeros(n_steps)

    # Initial condition: start at heating setpoint
    t_in = room.t_set_heating

    for i in range(n_steps):
        t_out  = t_out_arr[i]
        q_sol  = q_solar_arr[i]
        q_int  = room.internal_gains_w

        # Free-float temperature update (Euler explicit)
        q_loss = H_total * (t_in - t_out)
        dT_dt  = (q_sol + q_int - q_loss) / C
        t_free = t_in + dT_dt * dt

        # Apply HVAC: clamp to setpoint band
        if t_free < room.t_set_heating:
            q_heat = C * (room.t_set_heating - t_free) / dt
            t_in   = room.t_set_heating
        elif t_free > room.t_set_cooling:
            q_cool = C * (t_free - room.t_set_cooling) / dt
            t_in   = room.t_set_cooling
            q_heat = 0.0
        else:
            t_in   = t_free
            q_heat = 0.0
            q_cool = 0.0

        t_in_arr[i]   = t_in
        q_heat_arr[i] = q_heat
        q_cool_arr[i] = q_cool if t_free > room.t_set_cooling else 0.0

    results = pd.DataFrame({
        "t_in":        t_in_arr,
        "t_out":       t_out_arr,
        "q_solar":     q_solar_arr,
        "q_internal":  room.internal_gains_w,
        "q_cond_loss": ua_env * (t_in_arr - t_out_arr),
        "q_vent_loss": H_ve  * (t_in_arr - t_out_arr),
        "q_heating":   q_heat_arr,
        "q_cooling":   q_cool_arr,
    }, index=weather_df.index)

    return results


def annual_summary(sim: pd.DataFrame, room: Room) -> dict:
    """Key annual energy and comfort metrics from simulation results."""
    E_heat = sim["q_heating"].sum() / 1000  # kWh (1h timestep → /1000 W→kWh)
    E_cool = sim["q_cooling"].sum() / 1000

    return {
        "E_heating_kWh":          round(E_heat, 0),
        "E_cooling_kWh":          round(E_cool, 0),
        "E_heating_kWh_m2":       round(E_heat / room.floor_area, 1),
        "E_cooling_kWh_m2":       round(E_cool / room.floor_area, 1),
        "peak_heating_W":         round(sim["q_heating"].max(), 0),
        "peak_cooling_W":         round(sim["q_cooling"].max(), 0),
        "t_in_mean":              round(sim["t_in"].mean(), 1),
        "solar_gains_kWh":        round(sim["q_solar"].sum() / 1000, 0),
        "internal_gains_kWh":     round(sim["q_internal"].sum() / 1000, 0),
        "cond_losses_kWh":        round(sim["q_cond_loss"].clip(lower=0).sum() / 1000, 0),
        "vent_losses_kWh":        round(sim["q_vent_loss"].clip(lower=0).sum() / 1000, 0),
    }
