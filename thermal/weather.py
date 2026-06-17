"""
Weather data fetching from Open-Meteo (free, no API key needed).
Returns hourly TMY-like data for a given location and year.
"""

import httpx
import pandas as pd


OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"


def fetch_weather(
    lat: float,
    lon: float,
    year: int = 2023,
    timeout: float = 30.0,
) -> pd.DataFrame:
    """
    Fetch one year of hourly weather from Open-Meteo historical archive.

    Returns DataFrame with DatetimeIndex (UTC) and columns:
      - t_out        : outdoor dry-bulb temperature [°C]
      - ghi          : global horizontal irradiance [W/m²]
      - dhi          : diffuse horizontal irradiance [W/m²]
      - wind_speed   : wind speed at 10m [m/s]
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": f"{year}-01-01",
        "end_date": f"{year}-12-31",
        "hourly": [
            "temperature_2m",
            "shortwave_radiation",
            "diffuse_radiation",
            "wind_speed_10m",
        ],
        "timezone": "UTC",
    }

    resp = httpx.get(OPEN_METEO_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    hourly = data["hourly"]
    df = pd.DataFrame({
        "t_out":      hourly["temperature_2m"],
        "ghi":        hourly["shortwave_radiation"],
        "dhi":        hourly["diffuse_radiation"],
        "wind_speed": hourly["wind_speed_10m"],
    }, index=pd.to_datetime(hourly["time"]))

    df.index.name = "time_utc"
    df = df.ffill().fillna(0)
    return df


def weather_stats(df: pd.DataFrame) -> dict:
    """Key statistics from a weather DataFrame."""
    return {
        "t_min":  round(df["t_out"].min(), 1),
        "t_max":  round(df["t_out"].max(), 1),
        "t_mean": round(df["t_out"].mean(), 1),
        "HDD_18": round(((18 - df["t_out"]).clip(lower=0)).sum() / 24, 0),  # heating degree-days base 18°C
        "CDD_26": round(((df["t_out"] - 26).clip(lower=0)).sum() / 24, 0),  # cooling degree-days base 26°C
        "ghi_annual_kWh_m2": round(df["ghi"].sum() / 1000, 0),
    }
