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


def _to_rfc3339(ts: str) -> str:
    """
    Normalise an ISO-8601 string to the RFC 3339 form that InfluxDB v1 accepts
    (``YYYY-MM-DDTHH:MM:SSZ``).  Naive inputs are treated as UTC.

    Examples
    --------
    ``2024-01-01``              → ``2024-01-01T00:00:00Z``
    ``2024-01-01T12:00``        → ``2024-01-01T12:00:00Z``
    ``2024-01-01T12:00:00``     → ``2024-01-01T12:00:00Z``
    ``2024-01-01T12:00:00Z``    → ``2024-01-01T12:00:00Z``
    ``2024-01-01T12:00:00+02:00`` → returned unchanged (already RFC 3339)
    """
    ts = ts.strip()

    # Already has a non-Z explicit offset — InfluxDB accepts +HH:MM, return as-is.
    if "+" in ts[10:] or (ts[10:].count("-") > 0 and "T" in ts):
        return ts

    # Strip trailing Z or "UTC" to normalise the core datetime string.
    if ts.endswith("Z"):
        core = ts[:-1]
    elif ts.endswith("UTC"):
        core = ts[:-3].strip()
    else:
        core = ts

    # Expand date-only → midnight UTC.
    if len(core) == 10:
        core += "T00:00:00"
    # Expand HH:MM (no seconds) → HH:MM:00.
    elif len(core) == 16 and "T" in core:
        core += ":00"

    return core + "Z"


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
    start:    ISO-8601 string (timezone-naive strings are treated as UTC)
    end:      ISO-8601 string (timezone-naive strings are treated as UTC)
    resample: pandas offset string, default '15min'
    """
    measurement, field, tags = parse_signal(signal)
    c = client or _make_client()

    # InfluxDB v1 rejects naive timestamps — ensure RFC3339 with a Z suffix.
    start_ts = _to_rfc3339(start)
    end_ts = _to_rfc3339(end)

    wheres = " ".join(f"AND \"{k}\" = '{v}'" for k, v in tags.items())
    tag_clause = f"\n{wheres}" if wheres else ""

    query = (
        f'SELECT "{field}" FROM "{measurement}"'
        f"\nWHERE time >= '{start_ts}' AND time < '{end_ts}'"
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
