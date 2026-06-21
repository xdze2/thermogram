"""Thin InfluxDB wrapper for the thermogram API.

Signal name convention:  measurement/field?tag_key=tag_value[&tag2=val2]

Examples:
    open_meteo/temperature_2m
    zigbee2mqtt/temperature?name=salon
    poa/irradiance?face=SE
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import pandas as pd
from influxdb import DataFrameClient

from .config import INFLUX_DB, INFLUX_HOST, INFLUX_PORT


def _make_client() -> DataFrameClient:
    return DataFrameClient(host=INFLUX_HOST, port=INFLUX_PORT, database=INFLUX_DB)


def parse_signal(signal: str) -> tuple[str, str, dict[str, str]]:
    """Parse 'measurement/field?tag=val' → (measurement, field, tags)."""
    # split off query string
    if "?" in signal:
        path, qs = signal.split("?", 1)
    else:
        path, qs = signal, ""

    parts = path.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"signal must be 'measurement/field[?tag=val]', got: {signal!r}")

    measurement, field = parts
    tags: dict[str, str] = {}
    if qs:
        for key, vals in parse_qs(qs, keep_blank_values=False).items():
            tags[key] = vals[0]

    return measurement, field, tags


def list_signals(client: DataFrameClient | None = None) -> list[str]:
    """Return all queryable signal names from InfluxDB.

    For each measurement, emits one entry per (field, tag-combination).
    Format: measurement/field  or  measurement/field?tag=val[&tag2=val2]
    """
    c = client or _make_client()
    signals: list[str] = []

    measurements_result = c.query("SHOW MEASUREMENTS")
    if not measurements_result:
        return signals
    measurements = [pt["name"] for pt in measurements_result.get_points()]

    for meas in measurements:
        # fields
        fields_result = c.query(f'SHOW FIELD KEYS FROM "{meas}"')
        field_names = [pt["fieldKey"] for pt in fields_result.get_points()] if fields_result else []
        if not field_names:
            continue

        # tag keys for this measurement
        tag_keys_result = c.query(f'SHOW TAG KEYS FROM "{meas}"')
        tag_keys = [pt["tagKey"] for pt in tag_keys_result.get_points()] if tag_keys_result else []

        if not tag_keys:
            for field in field_names:
                signals.append(f"{meas}/{field}")
        else:
            # enumerate all series (each series = one tag-value combination)
            series_result = c.query(f'SHOW SERIES FROM "{meas}"')
            series_keys = [pt["key"] for pt in series_result.get_points()] if series_result else []
            for series_key in series_keys:
                # series_key looks like: "measurement,tag1=val1,tag2=val2"
                tag_str = _parse_series_tags(series_key, tag_keys)
                for field in field_names:
                    entry = f"{meas}/{field}"
                    if tag_str:
                        entry += f"?{tag_str}"
                    signals.append(entry)

    return sorted(set(signals))


def _parse_series_tags(series_key: str, tag_keys: list[str]) -> str:
    """Extract tag=value pairs from an InfluxDB SHOW SERIES key string."""
    # key format: "measurement,tag1=val1,tag2=val2"
    parts = series_key.split(",")
    pairs: list[str] = []
    for part in parts[1:]:  # skip measurement name
        if "=" in part:
            k, v = part.split("=", 1)
            if k in tag_keys:
                pairs.append(f"{k}={v}")
    return "&".join(pairs)


def fetch_series(
    signal: str,
    start: str,
    end: str,
    resample: str = "15min",
    client: DataFrameClient | None = None,
) -> pd.Series:
    """Fetch a signal from InfluxDB, resample to uniform grid, return pd.Series.

    Parameters
    ----------
    signal:   'measurement/field?tag=val'
    start:    ISO-8601 string
    end:      ISO-8601 string
    resample: pandas offset string, default '15min'
    """
    measurement, field, tags = parse_signal(signal)
    c = client or _make_client()

    wheres = " ".join(f"AND \"{k}\" = '{v}'" for k, v in tags.items())
    tag_clause = f"\n{wheres}" if wheres else ""

    query = (
        f'SELECT "{field}" FROM "{measurement}"'
        f"\nWHERE time >= '{start}' AND time < '{end}'"
        f"{tag_clause}"
        f'\nORDER BY "time" ASC'
    )
    raw = c.query(query)
    if not raw:
        return pd.Series(dtype="float64", name=signal)

    df = next(iter(raw.values()))
    s = df[field].copy()
    s.index = pd.to_datetime(s.index, utc=True)
    s.name = signal

    # resample to uniform grid — mean for dense sensor data, interpolate for sparse (e.g. hourly meteo)
    s = s.resample(resample).mean()
    s = s.interpolate(method="time", limit=4)  # linear interpolation up to 4 × resample interval
    s = s.ffill(limit=4)  # fill remaining edge gaps (e.g. start of series)
    return s
