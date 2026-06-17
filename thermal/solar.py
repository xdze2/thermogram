"""
Solar geometry and irradiance on tilted surfaces.
Based on standard astronomical formulas (Spencer, Duffie & Beckman).
"""

import math
import numpy as np
import pandas as pd


def day_of_year(dt: pd.Timestamp) -> int:
    return dt.day_of_year


def solar_declination(doy: int) -> float:
    """Solar declination angle δ [radians]. Spencer equation."""
    b = 2 * math.pi * (doy - 1) / 365
    return (0.006918 - 0.399912 * math.cos(b) + 0.070257 * math.sin(b)
            - 0.006758 * math.cos(2*b) + 0.000907 * math.sin(2*b)
            - 0.002697 * math.cos(3*b) + 0.00148  * math.sin(3*b))


def equation_of_time(doy: int) -> float:
    """Equation of time [minutes]. Spencer equation."""
    b = 2 * math.pi * (doy - 1) / 365
    return 229.18 * (0.000075 + 0.001868 * math.cos(b) - 0.032077 * math.sin(b)
                     - 0.014615 * math.cos(2*b) - 0.04089 * math.sin(2*b))


def solar_angles(
    lat_deg: float,
    lon_deg: float,
    utc_hour: float,
    doy: int,
) -> tuple[float, float]:
    """
    Return (altitude, azimuth) of sun in radians.
    altitude: angle above horizon (negative = below)
    azimuth: measured from South, positive toward West (meteorological convention)
    """
    lat = math.radians(lat_deg)
    dec = solar_declination(doy)
    eot = equation_of_time(doy)
    # Local solar time
    lst = utc_hour + lon_deg / 15.0 + eot / 60.0
    hour_angle = math.radians(15.0 * (lst - 12.0))

    sin_alt = (math.sin(lat) * math.sin(dec)
               + math.cos(lat) * math.cos(dec) * math.cos(hour_angle))
    sin_alt = max(-1.0, min(1.0, sin_alt))
    altitude = math.asin(sin_alt)

    cos_alt = math.cos(altitude)
    if cos_alt < 1e-6:
        azimuth = 0.0
    else:
        sin_az = math.cos(dec) * math.sin(hour_angle) / cos_alt
        cos_az = (math.sin(dec) - math.sin(lat) * sin_alt) / (math.cos(lat) * cos_alt)
        azimuth = math.atan2(sin_az, cos_az)

    return altitude, azimuth


# Orientation to azimuth from South (radians), N hemisphere convention
_ORIENT_AZ = {
    "N":  math.pi,
    "NE": math.pi * 3/4,
    "E":  math.pi / 2,
    "SE": math.pi / 4,
    "S":  0.0,
    "SW": -math.pi / 4,
    "W":  -math.pi / 2,
    "NW": -math.pi * 3/4,
    "horizontal": 0.0,
}


def incidence_angle(
    altitude: float,
    azimuth: float,
    surface_tilt_deg: float,
    surface_orientation: str,
) -> float:
    """
    Angle of incidence of solar beam on a tilted surface [radians].
    Returns π/2 if sun is below horizon.
    """
    if altitude <= 0:
        return math.pi / 2

    tilt = math.radians(surface_tilt_deg)
    surf_az = _ORIENT_AZ.get(surface_orientation, 0.0)

    cos_i = (math.cos(altitude) * math.cos(azimuth - surf_az) * math.sin(tilt)
             + math.sin(altitude) * math.cos(tilt))
    cos_i = max(0.0, min(1.0, cos_i))
    return math.acos(cos_i)


def irradiance_on_surface(
    ghi: float,      # W/m²  global horizontal irradiance
    dhi: float,      # W/m²  diffuse horizontal irradiance
    altitude: float, # rad
    incidence: float,# rad
    surface_tilt_deg: float,
    albedo: float = 0.2,
) -> float:
    """
    Total irradiance on a tilted surface [W/m²].
    Uses isotropic sky diffuse model (Hottel-Woertz).
    """
    if ghi <= 0 or altitude <= 0:
        return 0.0

    dni = max(0.0, (ghi - dhi) / math.sin(altitude))  # direct normal
    tilt = math.radians(surface_tilt_deg)
    view_factor_sky  = (1 + math.cos(tilt)) / 2
    view_factor_ground = (1 - math.cos(tilt)) / 2

    beam   = dni * math.cos(incidence)
    diffuse = dhi * view_factor_sky
    reflected = ghi * albedo * view_factor_ground

    return max(0.0, beam + diffuse + reflected)


def solar_gains_series(
    weather_df: pd.DataFrame,
    lat_deg: float,
    lon_deg: float,
    surface_tilt_deg: float,
    orientation: str,
    shgc: float,
    area_m2: float,
) -> pd.Series:
    """
    Compute hourly solar heat gain through a glazed element [W].
    weather_df must have columns: ghi, dhi (W/m²) and a UTC DatetimeIndex.
    """
    gains = []
    for ts, row in weather_df.iterrows():
        doy  = ts.day_of_year
        hour = ts.hour + ts.minute / 60.0
        alt, az = solar_angles(lat_deg, lon_deg, hour, doy)
        inc = incidence_angle(alt, az, surface_tilt_deg, orientation)
        irr = irradiance_on_surface(
            row.get("ghi", 0), row.get("dhi", 0),
            alt, inc, surface_tilt_deg,
        )
        gains.append(irr * shgc * area_m2)

    return pd.Series(gains, index=weather_df.index)
