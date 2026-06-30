"""Runtime config — reads same env vars as miniha (MINIHA_INFLUX_*)."""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)


_REPO_ROOT = Path(__file__).resolve().parents[3]
_load_dotenv(Path(os.environ.get("MINIHA_ENV_FILE", _REPO_ROOT / ".env")))


INFLUX_HOST = os.environ.get("MINIHA_INFLUX_HOST", "localhost")
INFLUX_PORT = int(os.environ.get("MINIHA_INFLUX_PORT", "8086"))
INFLUX_DB   = os.environ.get("MINIHA_INFLUX_DB", "sensors2")

API_PORT    = int(os.environ.get("THERMALNODES_API_PORT", "8001"))
