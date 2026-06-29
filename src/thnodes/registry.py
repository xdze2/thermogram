"""
Type registry for elements and modules.

Provides JSON-serializable schemas so the frontend can render add/edit forms
generically without hardcoding every type.

ELEMENT_TYPES: type_name -> {ctor, fields: [{name, type, default?, options?}]}
MODULE_TYPES:  type_name -> {ctor, owns: [channel_name], params: [param_name]}
"""

from __future__ import annotations

from .elements import Floor, HeatSource, IndoorMass, OuterWall, Partition, Window
from .materials import materials_db
from .modules import DirectLoss, HeavyWall, RoomMass, SolarGainModule

_ORIENTATIONS = ["S", "SE", "SW", "E", "W", "NE", "NW", "N"]
_MATERIALS = list(materials_db.keys())
_FLOOR_BOUNDARIES = ["ground", "adjacent", "exposed"]

ELEMENT_TYPES: dict[str, dict] = {
    "OuterWall": {
        "ctor": OuterWall,
        "fields": [
            {"name": "area", "type": "float"},
            {"name": "orientation", "type": "enum", "options": _ORIENTATIONS},
            {"name": "layers", "type": "list[layer]"},
            {"name": "alpha", "type": "float", "default": 0.6},
        ],
    },
    "Window": {
        "ctor": Window,
        "fields": [
            {"name": "area", "type": "float"},
            {"name": "orientation", "type": "enum", "options": _ORIENTATIONS},
            {"name": "U", "type": "float"},
            {"name": "shgc", "type": "float"},
        ],
    },
    "Floor": {
        "ctor": Floor,
        "fields": [
            {"name": "area", "type": "float"},
            {"name": "boundary", "type": "enum", "options": _FLOOR_BOUNDARIES},
            {"name": "layers", "type": "list[layer]"},
        ],
    },
    "Partition": {
        "ctor": Partition,
        "fields": [
            {"name": "area", "type": "float"},
            {"name": "layers", "type": "list[layer]"},
        ],
    },
    "IndoorMass": {
        "ctor": IndoorMass,
        "fields": [
            {"name": "area", "type": "float", "default": 0.0},
            {"name": "C", "type": "float"},
        ],
    },
    "HeatSource": {
        "ctor": HeatSource,
        "fields": [
            {"name": "area", "type": "float", "default": 0.0},
        ],
    },
}

# Layer sub-schema (used by fields of type "list[layer]")
LAYER_SCHEMA: dict = {
    "fields": [
        {"name": "material", "type": "enum", "options": _MATERIALS},
        {"name": "thickness", "type": "float"},
    ]
}

MODULE_TYPES: dict[str, dict] = {
    "RoomMass": {
        "ctor": RoomMass,
        "owns": [],
        "params": ["C_room"],
        "fields": [
            {"name": "floor_area", "type": "float"},
        ],
    },
    "DirectLoss": {
        "ctor": DirectLoss,
        "owns": ["CONDUCTION"],
        "params": ["H_ve"],
        "fields": [],
    },
    "SolarGainModule": {
        "ctor": SolarGainModule,
        "owns": ["SOLAR_TRANSMISSION"],
        "params": ["shgcA"],
        "fields": [],
    },
    "HeavyWall": {
        "ctor": HeavyWall,
        "owns": ["CONDUCTION", "STORAGE", "SOLAR_OPAQUE"],
        "params": ["H_out", "H_in", "C_wall"],
        "fields": [],
    },
}
