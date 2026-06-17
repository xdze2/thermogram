"""
Per-orientation plane-of-array (POA) irradiance from GHI (+ optional direct/diffuse).

Given GPS coordinates, timestamps, and irradiance signals, returns a dict mapping
each orientation string (e.g. "S", "E", "horizontal") to a POA irradiance array [W/m²].

Only the orientations actually present in a room's element list are computed.

Tilt assumptions:
  - walls, doors : 90° (vertical)
  - roof         : ROOF_TILT_DEG (30°, fixed default)
  - floor        : 0° (horizontal, facing up — receives no direct solar)
  - horizontal   : 0°
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pvlib

from .api_models import ElementType, Orientation, Room

# Fixed roof tilt [degrees from horizontal]
ROOF_TILT_DEG = 30.0

# pvlib azimuth convention: 0=N, 90=E, 180=S, 270=W
_ORIENTATION_AZIMUTH: dict[str, float] = {
    "N":          0.0,
    "NE":        45.0,
    "E":         90.0,
    "SE":       135.0,
    "S":        180.0,
    "SW":       225.0,
    "W":        270.0,
    "NW":       315.0,
    "horizontal":  0.0,  # azimuth irrelevant for horizontal surfaces
    "roof":      180.0,  # assume south-facing roof slope (conservative); azimuth matters less at 30° tilt
    "floor":       0.0,  # downward-facing, no direct solar
}


def _tilt_for_element_type(etype: ElementType) -> float:
    if etype == ElementType.roof:
        return ROOF_TILT_DEG
    if etype == ElementType.floor:
        return 0.0
    return 90.0  # wall, door, window


def orientation_key(elem) -> str:
    """Return the G_i dict key for an element: orientation for walls/doors/windows, 'roof' for roofs, 'floor' for floors."""
    if elem.type == ElementType.roof:
        return "roof"
    if elem.type == ElementType.floor:
        return "floor"
    return elem.orientation.value


def orientations_in_room(room: Room) -> dict[str, float]:
    """Return {G_key: surface_tilt_deg} for all elements in room (opaque and windows)."""
    result: dict[str, float] = {}
    for elem in room.elements:
        key = orientation_key(elem)
        tilt = _tilt_for_element_type(elem.type)
        result.setdefault(key, tilt)
    return result


def compute_poa(
    lat: float,
    lon: float,
    timestamps: list[str],
    ghi: np.ndarray,
    direct: np.ndarray | None = None,
    diffuse: np.ndarray | None = None,
    orientations: dict[str, float] | None = None,
) -> dict[str, np.ndarray]:
    """
    Compute plane-of-array irradiance for each orientation.

    Parameters
    ----------
    lat, lon      : GPS coordinates [degrees]
    timestamps    : ISO-8601 strings (with or without timezone; UTC assumed if naive)
    ghi           : (N,) global horizontal irradiance [W/m²]
    direct        : (N,) direct (beam) horizontal irradiance [W/m²], optional
                    (Open-Meteo "direct_radiation")
    diffuse       : (N,) diffuse horizontal irradiance [W/m²], optional
                    (Open-Meteo "diffuse_radiation")
    orientations  : {orientation_str: surface_tilt_deg} — if None, returns empty dict

    Returns
    -------
    dict mapping each orientation key → (N,) POA global irradiance [W/m²]
    """
    if not orientations:
        return {}

    N = len(timestamps)
    ghi = np.asarray(ghi, dtype=float)

    # Build timezone-aware DatetimeIndex
    times = pd.DatetimeIndex([
        pd.Timestamp(ts) if "+" in ts or ts.endswith("Z") else pd.Timestamp(ts, tz="UTC")
        for ts in timestamps
    ])

    location = pvlib.location.Location(latitude=lat, longitude=lon, tz="UTC")
    solar_pos = location.get_solarposition(times)

    # Decompose GHI → DNI + DHI if not provided
    if direct is not None and diffuse is not None:
        # Open-Meteo direct_radiation is beam on horizontal → convert to DNI
        # DNI = direct_horizontal / cos(zenith),  clipped when sun is low
        cos_z = np.cos(np.radians(solar_pos["zenith"].values))
        cos_z_safe = np.maximum(cos_z, 0.087)  # clip at ~5° elevation
        dni = np.asarray(direct, dtype=float) / cos_z_safe
        dhi = np.asarray(diffuse, dtype=float)
    else:
        # Erbs decomposition from GHI only
        erbs = pvlib.irradiance.erbs(ghi, solar_pos["zenith"], times)
        dni = erbs["dni"].values
        dhi = erbs["dhi"].values

    result: dict[str, np.ndarray] = {}
    for orient_str, tilt in orientations.items():
        azimuth = _ORIENTATION_AZIMUTH[orient_str]
        poa = pvlib.irradiance.get_total_irradiance(
            surface_tilt=tilt,
            surface_azimuth=azimuth,
            solar_zenith=solar_pos["zenith"],
            solar_azimuth=solar_pos["azimuth"],
            dni=dni,
            ghi=ghi,
            dhi=dhi,
        )
        poa_vals = poa["poa_global"].values.astype(float)
        poa_vals = np.where(np.isnan(poa_vals), 0.0, poa_vals)
        poa_vals = np.maximum(poa_vals, 0.0)
        result[orient_str] = poa_vals

    return result
