import numpy as np

ORIENTATIONS = ("S", "SE", "SW", "E", "W", "NE", "NW", "N")

# Azimuth from south, positive east [degrees]
_AZIMUTH = {"S": 0, "SE": -45, "SW": 45, "E": -90, "W": 90, "NE": -135, "NW": 135, "N": 180}


def solar_boundary(
    orientation: str,
    eff_area: float,
    weather: dict,
) -> np.ndarray:
    """
    POA irradiance × effective area → absorbed flux time series [W].

    weather must contain:
      "GHI"  : global horizontal irradiance array [W/m²]
      "solar_altitude" : solar altitude angle array [degrees]
      "solar_azimuth"  : solar azimuth from south array [degrees]

    # TODO proper POA transposition (pvlib 8-orientation model)
    For now: simple cosine projection of GHI onto the tilted plane.
    Vertical surface (tilt=90°), so POA = GHI * cos(angle_of_incidence).
    Negative values clipped to zero (sun behind the surface).
    """
    if orientation not in _AZIMUTH:
        raise ValueError(f"Unknown orientation {orientation!r}. Choose from {ORIENTATIONS}.")

    GHI = np.asarray(weather["GHI"], dtype=float)
    alt_deg = np.asarray(weather["solar_altitude"], dtype=float)
    az_deg = np.asarray(weather["solar_azimuth"], dtype=float)

    alt = np.radians(alt_deg)
    az_surface = np.radians(_AZIMUTH[orientation])
    az_sun = np.radians(az_deg)

    # cos(AOI) for a vertical surface facing `orientation`
    cos_aoi = np.cos(alt) * np.cos(az_sun - az_surface)
    poa = np.clip(cos_aoi, 0.0, None) * GHI

    return eff_area * poa
