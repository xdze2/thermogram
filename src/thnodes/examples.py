"""
Canonical example rooms as serializable RoomDoc-shaped dicts.

Each example is stored as a JSON file under src/thnodes/examples/*.json and can
be loaded by the persistence layer for "new from example" functionality without
importing streamlit or any FastAPI runtime.

JSON shape matches RoomDoc/ElementSpec/ModuleSpec from api/models.py:

    {
        "name": "<human label>",
        "elements": {
            "e0": {"type": "<ElementType>", "fields": {...}},
            ...
        },
        "modules": {
            "m0": {"type": "<ModuleType>", "fields": {...}},
            ...
        },
        "routes": {
            "m0": [],           # module_id -> [element_ids]
            "m1": ["e0", "e1"],
            ...
        }
    }

Element and module IDs are assigned sequentially: "e0", "e1", ... / "m0", "m1", ...
consistent with the counter-based scheme in RoomDoc.

Room descriptions are ported from notebooks/case_rooms.py (the now-deleted
streamlit prototype), which was the single prior source of canonical room
definitions.

Usage
-----
    from thnodes.examples import list_examples, load_example

    for meta in list_examples():
        print(meta["key"], meta["name"])

    doc_dict = load_example("caravan")
"""

from __future__ import annotations

import json
from pathlib import Path

_EXAMPLES_DIR = Path(__file__).parent / "examples"


# ── RoomDoc-shaped dict builders ──────────────────────────────────────────────


def _caravan() -> dict:
    """
    Caravan — all-light, single fast band.

    RoomMass + DirectLoss (wall + window) + SolarGainModule (window).
    No heavy mass → single T_room state.  Fast time constant.
    """
    return {
        "name": "Caravan",
        "elements": {
            "e0": {
                "type": "OuterWall",
                "fields": {
                    "area": 12.0,
                    "orientation": "S",
                    "layers": [{"material": "insulation_mineral_wool", "thickness": 0.05}],
                    "alpha": 0.6,
                },
            },
            "e1": {
                "type": "Window",
                "fields": {
                    "area": 3.0,
                    "orientation": "S",
                    "U": 2.8,
                    "shgc": 0.7,
                },
            },
        },
        "modules": {
            "m0": {"type": "RoomMass", "fields": {"floor_area": 15.0}},
            "m1": {"type": "DirectLoss", "fields": {}},
            "m2": {"type": "SolarGainModule", "fields": {}},
        },
        "routes": {
            "m0": [],
            "m1": ["e0", "e1"],
            "m2": ["e1"],
        },
    }


def _heavy_wall() -> dict:
    """
    Heavy-wall — two bands, good excitation.

    RoomMass + DirectLoss (window) + HeavyWall (concrete wall) + SolarGainModule (window).
    T_wall (slow) + T_room (fast).  Independent diurnal signals → both bands identifiable.
    """
    return {
        "name": "Heavy-wall",
        "elements": {
            "e0": {
                "type": "OuterWall",
                "fields": {
                    "area": 20.0,
                    "orientation": "S",
                    "layers": [
                        {"material": "concrete", "thickness": 0.25},
                        {"material": "insulation_mineral_wool", "thickness": 0.1},
                    ],
                    "alpha": 0.6,
                },
            },
            "e1": {
                "type": "Window",
                "fields": {
                    "area": 4.0,
                    "orientation": "S",
                    "U": 1.2,
                    "shgc": 0.6,
                },
            },
        },
        "modules": {
            "m0": {"type": "RoomMass", "fields": {"floor_area": 20.0}},
            "m1": {"type": "DirectLoss", "fields": {}},
            "m2": {"type": "HeavyWall", "fields": {}},
            "m3": {"type": "SolarGainModule", "fields": {}},
        },
        "routes": {
            "m0": [],
            "m1": ["e1"],
            "m2": ["e0"],
            "m3": ["e1"],
        },
    }


def _collinear() -> dict:
    """
    Collinear — heavy-wall topology with correlated T_ext/G_sol inputs.

    Same physical topology as Heavy-wall.  The 'collinear' label signals that
    passive diurnal data (T_ext ∝ G_sol) is expected: the identifiability lens
    will flag slow-band params as borderline or prior_dominated.
    """
    base = _heavy_wall()
    base["name"] = "Collinear"
    return base


def _cellar() -> dict:
    """
    Cellar — ground-coupled, near-constant interior.

    RoomMass + DirectLoss (small north window to T_ext).  No solar module — the
    window's SOLAR_TRANSMISSION channel is intentionally unclaimed, which the
    assembler will warn about.  HeavySlab deferred until a T_ground signal is
    available.
    """
    return {
        "name": "Cellar",
        "elements": {
            "e0": {
                "type": "Window",
                "fields": {
                    "area": 1.0,
                    "orientation": "N",
                    "U": 2.0,
                    "shgc": 0.1,
                },
            },
        },
        "modules": {
            "m0": {"type": "RoomMass", "fields": {"floor_area": 25.0}},
            "m1": {"type": "DirectLoss", "fields": {}},
        },
        "routes": {
            "m0": [],
            "m1": ["e0"],
        },
    }


# ── registry ──────────────────────────────────────────────────────────────────

# Ordered list of (key, builder) pairs.  The key is the JSON file stem and the
# argument to load_example().
_REGISTRY: list[tuple[str, object]] = [
    ("caravan", _caravan),
    ("heavy_wall", _heavy_wall),
    ("collinear", _collinear),
    ("cellar", _cellar),
]


# ── public API ────────────────────────────────────────────────────────────────


def list_examples() -> list[dict[str, str]]:
    """
    Return a list of ``{"key": ..., "name": ...}`` dicts for every available
    example, in canonical order.

    The ``key`` is a stable identifier (the JSON file stem) suitable for use as
    an API path parameter.  The ``name`` is the human-readable label stored in
    the JSON itself.
    """
    result = []
    for key, _ in _REGISTRY:
        path = _EXAMPLES_DIR / f"{key}.json"
        if path.exists():
            with path.open() as fh:
                data = json.load(fh)
            result.append({"key": key, "name": data.get("name", key)})
        else:
            # Fall back to the in-memory builder if the JSON file is missing
            # (should not happen in a properly installed package).
            result.append({"key": key, "name": key})
    return result


def load_example(key: str) -> dict:
    """
    Return the RoomDoc-shaped dict for the example identified by *key*.

    Reads from the committed JSON file under src/thnodes/examples/.

    Raises
    ------
    KeyError
        If *key* is not a known example.
    FileNotFoundError
        If the JSON file is missing (broken installation).
    """
    valid_keys = {k for k, _ in _REGISTRY}
    if key not in valid_keys:
        raise KeyError(f"Unknown example key {key!r}. Valid keys: {sorted(valid_keys)}")
    path = _EXAMPLES_DIR / f"{key}.json"
    with path.open() as fh:
        return json.load(fh)


# ── generate / regenerate the JSON seed files ─────────────────────────────────


def _write_examples() -> None:
    """
    Write (or overwrite) the JSON seed files under src/thnodes/examples/.

    Called once to generate the committed files.  The running system reads JSON;
    it does not call this function at startup.
    """
    _EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    for key, builder in _REGISTRY:
        data = builder()
        path = _EXAMPLES_DIR / f"{key}.json"
        with path.open("w") as fh:
            json.dump(data, fh, indent=2)
        print(f"Wrote {path}")


if __name__ == "__main__":
    _write_examples()
