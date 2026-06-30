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
from .modules import DirectLoss, HeavyWall, RoomMass, SolarGainModule, SourceFluxModule

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
            # D1 treatment field: "" = forced default; heavy walls may carry "simple_loss".
            {"name": "treatment", "type": "str", "default": ""},
        ],
        # orientation pins T_ext (conduction) + G_sol_<orient> (opaque solar for heavy walls).
        "boundary": {"field": "orientation", "role": "exterior"},
        # Heavy walls may be modelled as simple loss (the one genuine authoring knob).
        # Light walls always get simple_loss (forced — no menu entry rendered for them).
        "treatments": [
            {"key": "thermal_mass", "label": "Thermal-mass wall", "default": True},
            {"key": "simple_loss", "label": "Simple loss", "default": False},
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
        # orientation pins T_ext + G_sol_<orient> (transmitted solar).
        "boundary": {"field": "orientation", "role": "exterior"},
        # Glazing treatment is forced — no user menu.
        "treatments": [],
    },
    "Floor": {
        "ctor": Floor,
        "fields": [
            {"name": "area", "type": "float"},
            {"name": "boundary", "type": "enum", "options": _FLOOR_BOUNDARIES},
            {"name": "layers", "type": "list[layer]"},
            # D1 field: room label used when boundary == "adjacent".
            {"name": "adjacent_room", "type": "str", "default": ""},
        ],
        # Role depends on the chosen boundary value ("ground", "adjacent", "exposed").
        "boundary": {"field": "boundary", "role": "by_value"},
        # Floor treatment is forced by the boundary value — no user menu.
        "treatments": [],
    },
    "Partition": {
        "ctor": Partition,
        "fields": [
            {"name": "area", "type": "float"},
            {"name": "layers", "type": "list[layer]"},
            # D1 field: label of the adjacent room this partition faces.
            {"name": "adjacent", "type": "str", "default": ""},
        ],
        # adjacent field pins T_<room> signal.
        "boundary": {"field": "adjacent", "role": "adjacent"},
        # Partition treatment is forced (interior loss) — no user menu.
        "treatments": [],
    },
    "IndoorMass": {
        "ctor": IndoorMass,
        "fields": [
            {"name": "a", "type": "float"},
            {"name": "b", "type": "float"},
            {"name": "c", "type": "float"},
            {
                "name": "furniture",
                "type": "enum",
                "options": ["bare", "normal", "heavy"],
                "default": "normal",
            },
        ],
        # Interior element — no boundary signal; auto-paired to RoomMass.
        "boundary": None,
        # Room-mass treatment is forced and auto-assigned — no user menu.
        "treatments": [],
    },
    "HeatSource": {
        "ctor": HeatSource,
        "fields": [
            {"name": "area", "type": "float", "default": 0.0},
            # D3: prescribed flux signal label (e.g. "hvac" → signal name "Q_hvac").
            # A non-empty value wires this element to SourceFlux[Q_<signal>].
            {"name": "signal", "type": "str", "default": ""},
        ],
        # HeatSource pins a prescribed flux signal (name chosen by the author).
        "boundary": {"field": "signal", "role": "prescribed"},
        # Prescribed-flux treatment is forced — no user menu.
        "treatments": [],
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
        "fields": [],
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
    "SourceFlux": {
        "ctor": SourceFluxModule,
        "owns": [],
        "params": [],
        "fields": [],
    },
}
