"""
Canonical example rooms as serializable RoomDoc-shaped dicts.

Each example is stored as a JSON file under src/thnodes/examples/*.json and can
be loaded by the persistence layer for "new from example" functionality without
importing streamlit or any FastAPI runtime.

JSON shape (D3 signal-grouping model — modules and routes are OMITTED):

    {
        "name": "<human label>",
        "elements": {
            "e0": {"type": "<ElementType>", "fields": {...}},
            ...
        }
        // "modules" and "routes" keys are absent; they are derived at read-time
        // by the grouping rule (doc_to_group).  Old JSON that still carries these
        // keys loads gracefully — they are kept as vestigial fields on RoomDoc
        // for load-compatibility but are no longer used for assembly.
    }

Element IDs are assigned sequentially: "e0", "e1", ...
consistent with the counter-based scheme in RoomDoc.

Per-element boundary / treatment fields (spec 15 / D1–D3):
  - OuterWall / Window: ``orientation`` (S…N) pins T_ext + G_sol_<orient>.
    Heavy OuterWall may carry ``treatment: "simple_loss"`` to override to
    DirectLoss[T_ext].
  - Floor: ``boundary`` ∈ {ground, adjacent, exposed}; when "adjacent",
    ``adjacent_room`` names the neighbouring space.
  - Partition: ``adjacent`` names the neighbouring room label.
  - IndoorMass: no boundary (auto-paired to RoomMass).
  - HeatSource: ``signal`` = prescribed-flux label (e.g. "hvac" → Q_hvac).

Modules are DERIVED by the grouping rule — the user never specifies them.

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

    IndoorMass (5×3×2.2 m, bare) + OuterWall (light insulation, S) + Window (S).
    Derived modules: RoomMass + DirectLoss[T_ext] + SolarGain[G_sol_S].
    No heavy mass → single T_room state.  Fast time constant.
    Required signals: T_ext, G_sol_S.
    """
    return {
        "name": "Caravan",
        "elements": {
            "e0": {
                "type": "IndoorMass",
                "fields": {
                    "a": 5.0,
                    "b": 3.0,
                    "c": 2.2,
                    "furniture": "bare",
                },
            },
            "e1": {
                "type": "OuterWall",
                "fields": {
                    "area": 12.0,
                    "orientation": "S",
                    "layers": [{"material": "insulation_mineral_wool", "thickness": 0.05}],
                    "alpha": 0.6,
                    # treatment="" → forced simple_loss for a light wall (no STORAGE budget).
                    "treatment": "",
                },
            },
            "e2": {
                "type": "Window",
                "fields": {
                    "area": 3.0,
                    "orientation": "S",
                    "U": 2.8,
                    "shgc": 0.7,
                },
            },
        },
    }


def _heavy_wall() -> dict:
    """
    Heavy-wall — two bands, good excitation.

    IndoorMass (5×4×2.5 m, normal) + OuterWall (concrete/insulation, S, heavy,
    treatment="thermal_mass") + Window (S).
    Derived modules: RoomMass + HeavyWall[T_ext] + DirectLoss[T_ext] + SolarGain[G_sol_S].
    T_wall (slow) + T_room (fast).  Required signals: T_ext, G_sol_S.
    """
    return {
        "name": "Heavy-wall",
        "elements": {
            "e0": {
                "type": "IndoorMass",
                "fields": {
                    "a": 5.0,
                    "b": 4.0,
                    "c": 2.5,
                    "furniture": "normal",
                },
            },
            "e1": {
                "type": "OuterWall",
                "fields": {
                    "area": 20.0,
                    "orientation": "S",
                    "layers": [
                        {"material": "concrete", "thickness": 0.25},
                        {"material": "insulation_mineral_wool", "thickness": 0.1},
                    ],
                    "alpha": 0.6,
                    # treatment="" → default for heavy wall = thermal_mass → HeavyWall[T_ext].
                    "treatment": "",
                },
            },
            "e2": {
                "type": "Window",
                "fields": {
                    "area": 4.0,
                    "orientation": "S",
                    "U": 1.2,
                    "shgc": 0.6,
                },
            },
        },
    }


def _collinear() -> dict:
    """
    Collinear — heavy-wall topology with correlated T_ext/G_sol inputs.

    Same physical topology as Heavy-wall.  The 'collinear' label signals that
    passive diurnal data (T_ext ∝ G_sol) is expected: the identifiability lens
    will flag slow-band params as borderline or prior_dominated.
    Derived modules: same as heavy_wall.
    """
    base = _heavy_wall()
    base["name"] = "Collinear"
    return base  # elements are identical; derived modules will match heavy_wall


def _cellar() -> dict:
    """
    Cellar — ground-coupled, near-constant interior.

    IndoorMass (5×5×2.2 m, heavy furniture/stored items) + small north Window (N).
    Derived modules: RoomMass + DirectLoss[T_ext] + SolarGain[G_sol_N].
    The window's SOLAR_TRANSMISSION channel is now claimed by SolarGain[G_sol_N]
    (the grouping rule auto-derives a solar gain module for any window).
    Required signals: T_ext, G_sol_N.
    """
    return {
        "name": "Cellar",
        "elements": {
            "e0": {
                "type": "IndoorMass",
                "fields": {
                    "a": 5.0,
                    "b": 5.0,
                    "c": 2.2,
                    "furniture": "heavy",
                },
            },
            "e1": {
                "type": "Window",
                "fields": {
                    "area": 1.0,
                    "orientation": "N",
                    "U": 2.0,
                    "shgc": 0.1,
                },
            },
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
