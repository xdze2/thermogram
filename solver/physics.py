"""House model → RC network expansion.

expand(house) → (model_dict, expansion_map)

Each room/element carries a `role` field:
  - "mass"     : temperature is unknown, solved for (default for rooms)
  - "boundary" : temperature is prescribed by an input signal (obs_signal)
  - "fixed"    : temperature is a known constant (e.g. ground = 10 °C)

outdoor/ground elements are always boundary nodes regardless of role.

expansion_map: { house_uuid → list[rc_node_id] }
  Maps each house room/element UUID to the RC node ids it produced.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid as _uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_MATERIALS_DIR = Path(__file__).parents[1] / "data" / "materials"


def load_material_library() -> dict[str, dict]:
    """Load all *.json files from data/materials/ into a flat dict keyed by id."""
    lib: dict[str, dict] = {}
    if _MATERIALS_DIR.is_dir():
        for path in _MATERIALS_DIR.glob("*.json"):
            with open(path) as f:
                entry = json.load(f)
            mid = entry.get("id") or path.stem
            lib[mid] = entry
    return lib


_MATERIAL_LIBRARY: dict[str, dict] = load_material_library()

# ISO 6946 surface resistance defaults [m²·K/W]
_RSI_INTERIOR = 1.0 / 7.7   # h_i = 7.7 W/(m²·K)
_RSI_EXTERIOR = 1.0 / 25.0  # h_e = 25.0 W/(m²·K)

# Air properties for ACH → R conversion
_RHO_AIR = 1.2        # kg/m³
_CP_AIR  = 1006.0     # J/(kg·K)
_CP_AIR_KJ = _CP_AIR / 3600.0  # J/(kg·K) → Wh/(kg·K), used for ACH [h⁻¹] arithmetic


def model_hash(elements: list) -> str:
    """SHA-256 of canonical JSON of elements list, first 12 hex chars."""
    canonical = json.dumps(elements, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


@dataclass
class _Builder:
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    expansion_map: dict[str, list[str]] = field(default_factory=dict)
    # wall_chains: element_label → {mass_ids, r_ids, chain_n}
    # Used by _patch_model to fan out (element.R, element.C) to lump nodes.
    wall_chains: dict[str, dict] = field(default_factory=dict)
    _node_ids: set[str] = field(default_factory=set)

    def _unique_id(self, base: str) -> str:
        candidate = base
        n = 2
        while candidate in self._node_ids:
            candidate = f"{base}_{n}"
            n += 1
        self._node_ids.add(candidate)
        return candidate

    def add_node(self, node: dict, house_uuid: str | None = None) -> str:
        nid = node["id"]
        self._node_ids.add(nid)
        self.nodes.append(node)
        if house_uuid is not None:
            self.expansion_map.setdefault(house_uuid, []).append(nid)
        return nid

    def add_edge(self, from_id: str, to_id: str) -> None:
        self.edges.append({"from": from_id, "to": to_id})

    def has_node(self, nid: str) -> bool:
        return nid in self._node_ids

    def make_id(self, base: str) -> str:
        return self._unique_id(base)


def _safe_label(obj: dict) -> str:
    return obj.get("label") or obj.get("id", "")


def _room_volume(room: dict) -> float:
    return room["a"] * room["b"] * room["c"]


def _room_capacitance(room: dict) -> float:
    V = _room_volume(room)
    factor = room.get("furniture_factor", 2.5)
    return _RHO_AIR * _CP_AIR * V * factor


def _opaque_R_total(element: dict, materials: dict) -> float:
    """ISO 6946: R_total = R_si + sum(d/λ) + R_se, in K/W (not m²·K/W — area applied later)."""
    h_i = element.get("h_i", 7.7)
    h_e = element.get("h_e", 25.0)
    R_si = 1.0 / h_i
    R_se = 1.0 / h_e
    R_layers = 0.0
    for layer in element["layers"]:
        mat_id = layer["material"]
        if mat_id not in materials:
            label = _safe_label(element)
            available = sorted(materials.keys())
            raise KeyError(
                f"Unknown material '{mat_id}' in element '{label}'. "
                f"Available: {available}"
            )
        R_layers += layer["thickness"] / materials[mat_id]["lambda"]
    area = element["a"] * element["b"]
    # Convert m²·K/W → K/W
    return (R_si + R_layers + R_se) / area


def _opaque_C_total(element: dict, materials: dict) -> float:
    """Total wall thermal capacitance [J/K] = area × Σ(ρ·cp·d) over layers."""
    area = element["a"] * element["b"]
    C = 0.0
    for layer in element["layers"]:
        mat = materials[layer["material"]]
        C += mat["rho"] * mat["cp"] * layer["thickness"]
    return C * area


_OMEGA_24H = 2 * math.pi / 86400.0  # rad/s at 24h period


def _opaque_chain_n(element: dict, materials: dict) -> int:
    """Number of RC lumps needed to capture 24h thermal lag.

    chain_n = max over layers of ceil(d_layer / δ_layer)
    where δ = sqrt(2·α/ω), α = λ/(ρ·cp).
    Layers with zero mass (air gaps etc.) contribute 0 and are ignored.
    """
    n = 1
    for layer in element["layers"]:
        mat = materials[layer["material"]]
        rho_cp = mat["rho"] * mat["cp"]
        if rho_cp == 0:
            continue
        alpha = mat["lambda"] / rho_cp
        delta = math.sqrt(2 * alpha / _OMEGA_24H)
        n = max(n, math.ceil(layer["thickness"] / delta))
    return n


def _zone_node_kind(zone: dict) -> str:
    """Determine RC node kind from zone role + element kind."""
    kind = zone.get("kind")  # None for rooms
    if kind in ("outdoor", "ground"):
        return "boundary"
    role = zone.get("role", "mass")
    if role == "boundary":
        return "boundary"
    if role == "fixed":
        return "boundary"  # fixed T → boundary with constant T_source
    return "mass"


def _ensure_zone_node(
    zone_uuid: str,
    all_zones: dict[str, dict],
    builder: _Builder,
) -> str:
    """Ensure a zone (room, outdoor, ground) has a node; return its node id."""
    node_id = f"z_{zone_uuid.replace('-', '')}"

    if builder.has_node(node_id):
        return node_id

    zone = all_zones[zone_uuid]
    kind = zone.get("kind")  # None for rooms
    role = zone.get("role", "mass")

    if kind in ("outdoor", "ground"):
        if kind == "outdoor":
            T_source = zone.get("obs_signal") or "outdoor"
        else:
            T_source = zone.get("T_fixed", 10.0)
        builder.add_node(
            {"id": node_id, "kind": "boundary", "label": _safe_label(zone), "T_source": T_source},
            house_uuid=zone_uuid,
        )
    elif role == "boundary":
        T_source = zone.get("obs_signal") or zone.get("T_fixed", 20.0)
        builder.add_node(
            {"id": node_id, "kind": "boundary", "label": _safe_label(zone), "T_source": T_source},
            house_uuid=zone_uuid,
        )
    elif role == "fixed":
        T_source = zone.get("T_fixed", 20.0)
        builder.add_node(
            {"id": node_id, "kind": "boundary", "label": _safe_label(zone), "T_source": T_source},
            house_uuid=zone_uuid,
        )
    else:
        # role == "mass" (default)
        C = _room_capacitance(zone)
        builder.add_node(
            {"id": node_id, "kind": "mass", "label": _safe_label(zone), "C": C},
            house_uuid=zone_uuid,
        )

    return node_id


def _elem_base(element: dict) -> str:
    return element["id"].replace("-", "")


def _is_outdoor_node(node_id: str, builder: _Builder) -> bool:
    """Return True if the node is a boundary node representing outdoor/ground."""
    node = next((n for n in builder.nodes if n["id"] == node_id), None)
    return node is not None and node["kind"] == "boundary"


def _expand_opaque(
    element: dict,
    materials: dict,
    zone_a: str,
    zone_b: str,
    builder: _Builder,
    outdoor_solar_signal: str | None = None,
) -> None:
    """Opaque wall: N identical RC lumps flanked by fixed surface resistances.

    The chain runs from zone_a to zone_b; R_se is placed on the outdoor side,
    R_si on the indoor side.  Solar gain is injected into the outer surface
    mass node (the one adjacent to R_se).

    When element["no_mass"] is True the wall is approximated as a single
    resistor (total R, no capacitance).

    Topology (N=2, zone_a=outdoor, zone_b=room):
        outdoor — R_se — m_0(outer) — R/N — m_1(inner) — R_si — room
                           C/N                  C/N
                            ↑ solar gain
    """
    h_i = element.get("h_i", 7.7)
    h_e = element.get("h_e", 25.0)
    area = element["a"] * element["b"]
    R_se = (1.0 / h_e) / area
    R_si = (1.0 / h_i) / area

    R_total = _opaque_R_total(element, materials)
    R_wall = R_total - R_se - R_si
    C_wall = _opaque_C_total(element, materials)
    N = _opaque_chain_n(element, materials)

    # ── resistor-only approximation (no thermal mass) ─────────────────────────
    if element.get("no_mass", False):
        base = _elem_base(element)
        label = _safe_label(element)
        eid = element["id"]
        r_id = builder.make_id(f"R_{base}")
        builder.add_node(
            {"id": r_id, "kind": "resistance", "label": f"{label} (R)", "R": R_total},
            house_uuid=eid,
        )
        builder.add_edge(zone_a, r_id)
        builder.add_edge(r_id, zone_b)
        builder.wall_chains[label] = {
            "mass_ids": [],
            "r_ids": [r_id],
            "chain_n": 0,
            "R_wall": R_total,
            "C_wall": 0.0,
        }
        return

    base = _elem_base(element)
    label = _safe_label(element)
    eid = element["id"]

    # Determine which side is outdoor so R_se and solar are placed correctly.
    # zone_a is outdoor if it is a boundary node (outdoor/ground are always boundary).
    # If both or neither are boundary (two rooms), there is no outdoor surface:
    # place R_se on zone_a side arbitrarily and skip solar injection.
    a_is_outdoor = _is_outdoor_node(zone_a, builder)
    b_is_outdoor = _is_outdoor_node(zone_b, builder)
    outdoor_is_a = a_is_outdoor and not b_is_outdoor
    outdoor_is_b = b_is_outdoor and not a_is_outdoor
    has_outdoor_face = outdoor_is_a or outdoor_is_b

    # Place R_se on the outdoor side, R_si on the indoor side
    if outdoor_is_b:
        # chain: zone_a(room) — R_si — lumps — R_se — zone_b(outdoor)
        r_first = builder.make_id(f"Rsi_{base}")
        builder.add_node({"id": r_first, "kind": "resistance", "label": f"{label} (Rsi)", "R": R_si}, house_uuid=eid)
        r_last = builder.make_id(f"Rse_{base}")
        builder.add_node({"id": r_last, "kind": "resistance", "label": f"{label} (Rse)", "R": R_se}, house_uuid=eid)
    else:
        # chain: zone_a(outdoor or room) — R_se — lumps — R_si — zone_b
        r_first = builder.make_id(f"Rse_{base}")
        builder.add_node({"id": r_first, "kind": "resistance", "label": f"{label} (Rse)", "R": R_se}, house_uuid=eid)
        r_last = builder.make_id(f"Rsi_{base}")
        builder.add_node({"id": r_last, "kind": "resistance", "label": f"{label} (Rsi)", "R": R_si}, house_uuid=eid)

    builder.add_edge(zone_a, r_first)

    mass_ids: list[str] = []
    r_ids: list[str] = []
    prev = r_first
    for i in range(N):
        m_id = builder.make_id(f"m_{base}_{i}")
        if N == 1:
            node_label = f"{label} [wall]"
        elif i == 0 and outdoor_is_a:
            node_label = f"{label} [outer]"
        elif i == N - 1 and outdoor_is_b:
            node_label = f"{label} [outer]"
        elif (i == 0 and outdoor_is_b) or (i == N - 1 and outdoor_is_a):
            node_label = f"{label} [inner]"
        else:
            node_label = f"{label} [{i}]"
        builder.add_node({"id": m_id, "kind": "mass", "label": node_label, "C": C_wall / N}, house_uuid=eid)
        builder.add_edge(prev, m_id)
        mass_ids.append(m_id)

        if i < N - 1:
            r_id = builder.make_id(f"R_{base}_{i}")
            builder.add_node({"id": r_id, "kind": "resistance", "label": f"{label} (R{i})", "R": R_wall / N}, house_uuid=eid)
            builder.add_edge(m_id, r_id)
            r_ids.append(r_id)
            prev = r_id
        else:
            prev = m_id

    builder.add_edge(prev, r_last)
    builder.add_edge(r_last, zone_b)

    # Register chain for _patch_model fan-out: keyed by element label
    builder.wall_chains[label] = {
        "mass_ids": mass_ids,
        "r_ids": r_ids,
        "chain_n": N,
        "R_wall": R_wall,
        "C_wall": C_wall,
    }

    # Solar gain injected into the outer surface mass node
    alpha = element.get("solar_absorptance", 0.0)
    if alpha and outdoor_solar_signal and has_outdoor_face and mass_ids:
        # Outer surface node: m_0 when zone_a is outdoor, m_{N-1} when zone_b is outdoor
        outer_node = mass_ids[0] if outdoor_is_a else mass_ids[-1]
        area = element["a"] * element["b"]
        s_id = builder.make_id(f"solar_{base}")
        builder.add_node(
            {
                "id": s_id,
                "kind": "source",
                "label": f"{label} (solar)",
                "signal": outdoor_solar_signal,
                "gain": alpha * area,
            },
            house_uuid=eid,
        )
        builder.add_edge(s_id, outer_node)


def _expand_glazing(
    element: dict, zone_a: str, zone_b: str, builder: _Builder,
    outdoor_solar_signal: str | None = None,
) -> None:
    """Glazing: single resistance (from U-value) + optional solar source."""
    area = element["a"] * element["b"]
    R = 1.0 / (element["U"] * area)
    label = _safe_label(element)
    r_id = builder.make_id(f"R_{_elem_base(element)}")
    builder.add_node(
        {"id": r_id, "kind": "resistance", "label": f"{label} (U)", "R": R},
        house_uuid=element["id"],
    )
    builder.add_edge(zone_a, r_id)
    builder.add_edge(r_id, zone_b)

    if element.get("SHGC") and outdoor_solar_signal:
        shgc = element["SHGC"]
        s_id = builder.make_id(f"solar_{_elem_base(element)}")
        builder.add_node(
            {
                "id": s_id,
                "kind": "source",
                "label": f"{label} (solar)",
                "signal": outdoor_solar_signal,
                "gain": shgc * area,
            },
            house_uuid=element["id"],
        )
        builder.add_edge(s_id, zone_a)


def _expand_air_exchange(
    element: dict, room: dict, zone_a: str, zone_b: str, builder: _Builder
) -> None:
    """Air exchange (infiltration/ventilation): R = 1 / (ṁ·cp)."""
    V = _room_volume(room)
    ach = element["ach"]
    m_dot = _RHO_AIR * V * ach / 3600.0   # kg/s
    G = m_dot * _CP_AIR                    # W/K
    R = 1.0 / G
    label = _safe_label(element)
    r_id = builder.make_id(f"R_ach_{_elem_base(element)}")
    builder.add_node(
        {"id": r_id, "kind": "resistance", "label": label, "R": R},
        house_uuid=element["id"],
    )
    builder.add_edge(zone_a, r_id)
    builder.add_edge(r_id, zone_b)


def expand(house: dict) -> tuple[dict, dict[str, list[str]]]:
    """Expand a house model dict into an RC network model dict + expansion_map.

    Each room/element's `role` field controls node type:
      - "mass"     → mass node (temperature solved)
      - "boundary" → boundary node (T prescribed by obs_signal)
      - "fixed"    → boundary node (T fixed to T_fixed constant)
    outdoor/ground elements are always boundary nodes.

    Returns
    -------
    model:          RC network dict conforming to model.schema.json v0.3.
    expansion_map:  { house_uuid → [rc_node_ids] }
    """
    materials = {**_MATERIAL_LIBRARY, **house.get("materials", {})}

    # Build a flat lookup: uuid → room or element dict
    all_zones: dict[str, dict] = {}
    for room in house.get("rooms", []):
        all_zones[room["id"]] = room
    for elem in house.get("elements", []):
        all_zones[elem["id"]] = elem

    builder = _Builder()

    # Find the outdoor element's solar_signal for glazing nodes
    outdoor_solar_signal: str | None = None
    for elem in house.get("elements", []):
        if elem.get("kind") == "outdoor" and elem.get("solar_signal"):
            outdoor_solar_signal = elem["solar_signal"]
            break

    # Pre-create all room zone nodes
    for room in house.get("rooms", []):
        _ensure_zone_node(room["id"], all_zones, builder)

    # Elements
    for elem in house.get("elements", []):
        kind = elem["kind"]

        if kind in ("outdoor", "ground"):
            continue  # created on demand when referenced

        between = elem.get("between", [])
        if len(between) != 2:
            continue

        uuid_a, uuid_b = between[0], between[1]

        # Skip if both sides are mass nodes that don't exist yet
        # (shouldn't happen since we pre-create rooms, but be safe)
        zone_a = _ensure_zone_node(uuid_a, all_zones, builder)
        zone_b = _ensure_zone_node(uuid_b, all_zones, builder)

        if kind == "opaque":
            _expand_opaque(elem, materials, zone_a, zone_b, builder, outdoor_solar_signal)
        elif kind == "glazing":
            _expand_glazing(elem, zone_a, zone_b, builder, outdoor_solar_signal)
        elif kind == "air_exchange":
            room_uuid = uuid_a if uuid_a in {r["id"] for r in house.get("rooms", [])} else uuid_b
            room_dict = all_zones[room_uuid]
            _expand_air_exchange(elem, room_dict, zone_a, zone_b, builder)

    # Room input signals → source nodes
    for room in house.get("rooms", []):
        zone_id = f"z_{room['id'].replace('-', '')}"
        if room.get("input_signal"):
            src_id = builder.make_id(f"Q_{room['id'].replace('-', '')}")
            builder.add_node(
                {
                    "id": src_id,
                    "kind": "source",
                    "label": f"{_safe_label(room)} (input)",
                    "signal": room["input_signal"],
                    "gain": 1.0,
                },
                house_uuid=room["id"],
            )
            builder.add_edge(src_id, zone_id)

    model_id = f"expanded_{_uuid.uuid4().hex[:8]}"
    model = {
        "schema_version": "0.3",
        "id": model_id,
        "name": house.get("label", "Expanded model"),
        "nodes": builder.nodes,
        "edges": builder.edges,
        "wall_chains": builder.wall_chains,
    }

    return model, builder.expansion_map
