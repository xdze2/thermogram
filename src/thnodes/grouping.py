"""
D2 — The grouping rule (spec 15 §"Grouping rule"; spec 40 I8).

Public API
----------
derive_signals(elements)  -> list[Signal]
    Auto-create the Signal objects that the given elements pin, applying the
    liveness invariant (only signals referenced by at least one element).

group(elements)           -> GroupResult
    Apply the deterministic (treatment, signal) → module grouping rule and
    return a GroupResult that the assembler can consume directly.

GroupResult.to_assembler() -> Assembler
    Convenience method: build a fully-wired Assembler from the GroupResult so
    that callers can go straight to ``asm.build()``.

Design notes
~~~~~~~~~~~~
- One module per distinct ``(module_type_name, boundary_signal_name)`` key.
  Two south windows → one SolarGain[G_sol_S]; south + west → two SolarGain
  modules; two partitions → kitchen → one DirectLoss[T_kitchen].

- The boundary signal name IS the grouping key.  ``DirectLoss("T_kitchen")``
  and ``DirectLoss("T_ext")`` are distinct modules identified by their signal.

- Module instances are parametric: DirectLoss(T_bnd_signal=...) etc.  The
  ``signal`` attribute on TopologyModule carries the boundary signal name.

- Treatment branch for OuterWall:
    * heavy (STORAGE budget present) + treatment=="" or "thermal_mass"
      → HeavyWall[T_ext]
    * heavy + treatment=="simple_loss"
      → DirectLoss[T_ext]
    * light (no STORAGE budget)
      → DirectLoss[T_ext]  (forced; treatment field ignored)

- The exactly-once check (I3) is an internal assertion on the rule's output,
  surfaced as Problems via the assembler, never user error.

- IndoorMass → RoomMass (auto-paired by Assembler; group() just passes it
  through add_element so the assembler can find it).

- HeatSource → SourceFlux[Q_<label>]: a HeatSource with a non-empty ``signal``
  field (e.g. ``signal="hvac"``) routes to ``SourceFlux[Q_hvac]`` and auto-creates
  a ``prescribed`` signal.  A HeatSource with an empty ``signal`` is a no-op.

- GroundLoss for Floor(boundary="ground") is not in the Step-0 catalogue.
  We route it to DirectLoss[T_ground] using the CONDUCTION budget; this is
  physically equivalent (lumped ground conductance) and keeps the grouping
  conservative.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .assembler import Assembler
from .channels import Channel
from .elements import (
    EnvelopeElement,
    Floor,
    HeatSource,
    IndoorMass,
    OuterWall,
    Partition,
    Window,
)
from .modules import DirectLoss, HeavyWall, RoomMass, SolarGainModule, SourceFluxModule, TopologyModule


# ── Signal (lightweight; mirrors api.models.Signal but without the API dependency) ──

@dataclass
class Signal:
    """
    A named boundary input derived from element boundaries (spec 15).

    This is the pure-engine representation (no Pydantic, no FastAPI).  The
    ``api.models.Signal`` dataclass has the same fields and can be constructed
    from one of these directly.

    Kept binding-agnostic: no ``source``/``data`` field (future layer).
    """

    id: str                       # stable opaque ID, e.g. "s_ext"
    name: str                     # ODE signal name, e.g. "T_ext", "G_sol_S"
    kind: str                     # "temperature" | "irradiance" | "flux"
    role: str                     # "exterior" | "ground" | "adjacent" | "solar" | "prescribed"
    meta: dict = field(default_factory=dict)  # role-specific hints, e.g. {"orientation": "S"}


# ── DerivedModule ─────────────────────────────────────────────────────────────

@dataclass
class DerivedModule:
    """
    One derived module entry produced by the grouping rule.

    Carries exactly the information the assembler needs:
    - ``module``: the TopologyModule instance (parametric boundary signal baked in).
    - ``elements``: the envelope elements claimed by this module.
    - ``channels_claimed``: the Channel values this module claims from those elements
      (needed for the exactly-once I3 check and prior derivation).
    - ``key``: ``(module_type_name, boundary_signal_name)`` — the grouping key
      used in ModuleType[Signal] notation.  RoomMass uses ``("RoomMass", None)``.
    """

    module: TopologyModule
    elements: list[EnvelopeElement]
    channels_claimed: list[Channel]
    key: tuple[str, str | None]  # (module_type_name, boundary_signal_name | None)

    @property
    def type_name(self) -> str:
        """Module type name, e.g. "DirectLoss", "SolarGain", "HeavyWall"."""
        return self.key[0]

    @property
    def signal_name(self) -> str | None:
        """Boundary signal name, e.g. "T_ext", "G_sol_S".  None for RoomMass."""
        return self.key[1]


@dataclass
class GroupResult:
    """
    Result of the grouping rule: the full derived module set + the auto-created
    Signal objects for the model's boundary inputs.

    Call ``to_assembler()`` to get a ready-to-build Assembler.
    """

    # Derived modules in a stable order: RoomMass first, then others.
    derived_modules: list[DerivedModule]
    # Auto-created signals (liveness: only signals referenced by at least one element).
    signals: list[Signal]
    # All IndoorMass elements found (passed through to Assembler.add_element so the
    # assembler can detect multiples and emit a multiple_room_mass problem).
    _indoor_masses: list[IndoorMass] = field(default_factory=list, repr=False)

    def to_assembler(self) -> Assembler:
        """
        Build a fully-wired Assembler from this GroupResult.

        - Adds all IndoorMass elements (the assembler uses the first and emits a
          problem if more than one is present).
        - Adds every derived module with its claimed elements.
        """
        asm = Assembler()
        for im in self._indoor_masses:
            asm.add_element(im)
        for dm in self.derived_modules:
            asm.add_module(dm.module, elements=dm.elements)
        return asm


# ── helpers ───────────────────────────────────────────────────────────────────

def _solar_signal_name(orientation: str) -> str:
    """Canonical irradiance signal name for a given orientation."""
    return f"G_sol_{orientation}"


def _adjacent_signal_name(room_label: str) -> str:
    """Canonical temperature signal name for an adjacent room."""
    return f"T_{room_label}"


def _is_heavy_wall(wall: OuterWall) -> bool:
    """A wall is heavy iff its layers carry a STORAGE budget (rho > 500)."""
    return Channel.STORAGE in wall.channels()


# ── derive_signals ────────────────────────────────────────────────────────────

def derive_signals(elements: list[EnvelopeElement]) -> list[Signal]:
    """
    Auto-create the Signal objects that the given elements pin.

    Applies the liveness invariant (spec 15): only signals referenced by at
    least one element in ``elements`` are returned.  Order is stable:
    exterior first, then ground, then adjacent (sorted by room label), then
    solar (sorted by orientation), then prescribed (sorted by signal name).

    Parameters
    ----------
    elements:
        All envelope elements authored in the model (any ordering).

    Returns
    -------
    A list of Signal objects.  Each signal appears exactly once regardless of
    how many elements reference it.
    """
    needs_exterior = False
    needs_ground = False
    adjacent_rooms: set[str] = set()
    solar_orientations: set[str] = set()
    prescribed_labels: set[str] = set()  # HeatSource signal labels (the part after "Q_")

    for elem in elements:
        if isinstance(elem, IndoorMass):
            continue  # no boundary signal

        if isinstance(elem, HeatSource):
            label = elem.signal.strip()
            if label:
                prescribed_labels.add(label)
            continue

        if isinstance(elem, OuterWall):
            needs_exterior = True
            if _is_heavy_wall(elem):
                solar_orientations.add(elem.orientation)
            # Light walls do not contribute solar (SOLAR_OPAQUE deferred for light walls).

        elif isinstance(elem, Window):
            needs_exterior = True
            solar_orientations.add(elem.orientation)

        elif isinstance(elem, Floor):
            if elem.boundary == "ground":
                needs_ground = True
            elif elem.boundary == "exposed":
                needs_exterior = True
            elif elem.boundary == "adjacent":
                label = elem.adjacent_room.strip()
                if label:
                    adjacent_rooms.add(label)

        elif isinstance(elem, Partition):
            label = elem.adjacent.strip()
            if label:
                adjacent_rooms.add(label)

    signals: list[Signal] = []

    if needs_exterior:
        signals.append(Signal(
            id="s_ext",
            name="T_ext",
            kind="temperature",
            role="exterior",
        ))

    if needs_ground:
        signals.append(Signal(
            id="s_ground",
            name="T_ground",
            kind="temperature",
            role="ground",
        ))

    for room in sorted(adjacent_rooms):
        signals.append(Signal(
            id=f"s_adj_{room}",
            name=_adjacent_signal_name(room),
            kind="temperature",
            role="adjacent",
            meta={"room": room},
        ))

    for orient in sorted(solar_orientations):
        signals.append(Signal(
            id=f"s_sol_{orient}",
            name=_solar_signal_name(orient),
            kind="irradiance",
            role="solar",
            meta={"orientation": orient},
        ))

    # Prescribed signals: author-created via HeatSource.signal (e.g. "hvac" → "Q_hvac").
    for label in sorted(prescribed_labels):
        signals.append(Signal(
            id=f"s_presc_{label}",
            name=f"Q_{label}",
            kind="flux",
            role="prescribed",
            meta={"label": label},
        ))

    return signals


# ── group ─────────────────────────────────────────────────────────────────────

def group(elements: list[EnvelopeElement]) -> GroupResult:
    """
    Apply the deterministic grouping rule (spec 15 §"Grouping rule"; I8).

    For each element, determine its treatment (from the element's treatment
    field or forced by element type) and the boundary signals it pins.  Group
    into ``(module_type, signal)`` keys; each key becomes one DerivedModule
    that spends the summed channel budgets of its claimed elements.

    Parameters
    ----------
    elements:
        All envelope elements in the model (any ordering).

    Returns
    -------
    GroupResult with derived_modules and auto-created signals.

    Notes on the treatment branch
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    The only genuine authoring knob is on OuterWall (heavy only):
        treatment="" or "thermal_mass"  →  HeavyWall[T_ext]
        treatment="simple_loss"         →  DirectLoss[T_ext]
    All other treatments are forced by element type.

    Module-key uniqueness
    ~~~~~~~~~~~~~~~~~~~~~
    The grouping key ``(type_name, signal_name)`` determines module identity:
    - "DirectLoss" + "T_ext"     = all light-wall/window conduction to outside
    - "DirectLoss" + "T_kitchen" = partition/floor conduction to kitchen
    - "SolarGain"  + "G_sol_S"  = south window solar transmission
    - "HeavyWall"  + "T_ext"    = heavy-wall R-C-R branch
    - "RoomMass"   + None        = room thermal mass (singleton)

    Parameter names within a DerivedModule
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    All DirectLoss modules share the same param name "H_ve" in their
    TopologyModule, but each is a distinct module instance with its own prior.
    The assembler resolves them as distinct branches because they are separate
    module instances.  The grouping rule names params by function, not signal;
    the signal name appears in the module's ``signal`` attribute and in the
    grouping key, not in the param name.
    """
    # Accumulate per-key lists of (element, channels_claimed)
    # key: (type_name, signal_name | None)
    # value: list of (element, list[Channel])
    grouped: dict[tuple[str, str | None], list[tuple[EnvelopeElement, list[Channel]]]] = {}

    indoor_masses: list[IndoorMass] = []
    room_mass_key: tuple[str, str | None] = ("RoomMass", None)

    def _add(key: tuple[str, str | None], elem: EnvelopeElement, channels: list[Channel]) -> None:
        grouped.setdefault(key, []).append((elem, channels))

    for elem in elements:

        # ── IndoorMass → RoomMass (auto-paired by Assembler) ──────────────────
        if isinstance(elem, IndoorMass):
            indoor_masses.append(elem)
            # RoomMass entry: no element needed (assembler auto-routes IndoorMass).
            grouped.setdefault(room_mass_key, [])
            continue

        # ── HeatSource → SourceFlux[Q_<label>] ────────────────────────────────
        if isinstance(elem, HeatSource):
            label = elem.signal.strip()
            if label:
                # A HeatSource with a non-empty signal routes to SourceFlux.
                # HeatSource.channels() returns {} so no channels are claimed
                # here; the exactly-once check remains satisfied trivially.
                _add(("SourceFlux", f"Q_{label}"), elem, [])
            # HeatSource with empty signal: no-op (no module produced).
            continue

        # ── OuterWall ─────────────────────────────────────────────────────────
        if isinstance(elem, OuterWall):
            heavy = _is_heavy_wall(elem)
            treatment = elem.treatment.strip()

            if heavy and treatment != "simple_loss":
                # Default treatment for heavy wall: HeavyWall[T_ext]
                _add(("HeavyWall", "T_ext"), elem,
                     [Channel.CONDUCTION, Channel.STORAGE, Channel.SOLAR_OPAQUE])
            else:
                # Light wall (forced) or heavy wall with simple_loss override:
                # DirectLoss[T_ext]
                _add(("DirectLoss", "T_ext"), elem, [Channel.CONDUCTION])
                # Note: light walls' SOLAR_OPAQUE channel is not yet modelled
                # (DEFERRED — see TODO.md "Sol-air on light walls").  Heavy walls
                # overridden to simple_loss also drop SOLAR_OPAQUE here; the
                # STORAGE budget is likewise dropped (not claimed by any module).
                # This is consistent with the spec's treatment override intent:
                # simple_loss means "ignore thermal mass".
            continue

        # ── Window ────────────────────────────────────────────────────────────
        if isinstance(elem, Window):
            orient = elem.orientation
            # Conduction → DirectLoss[T_ext]
            _add(("DirectLoss", "T_ext"), elem, [Channel.CONDUCTION])
            # Solar transmission → SolarGain[G_sol_<orient>]
            sol_sig = _solar_signal_name(orient)
            _add(("SolarGain", sol_sig), elem, [Channel.SOLAR_TRANSMISSION])
            continue

        # ── Floor ─────────────────────────────────────────────────────────────
        if isinstance(elem, Floor):
            bnd = elem.boundary
            if bnd == "ground":
                # DirectLoss[T_ground] (GroundLoss not yet in catalogue; same physics)
                _add(("DirectLoss", "T_ground"), elem, [Channel.CONDUCTION])
            elif bnd == "exposed":
                _add(("DirectLoss", "T_ext"), elem, [Channel.CONDUCTION])
            elif bnd == "adjacent":
                label = elem.adjacent_room.strip()
                sig = _adjacent_signal_name(label) if label else "T_unknown"
                _add(("DirectLoss", sig), elem, [Channel.CONDUCTION])
            continue

        # ── Partition ─────────────────────────────────────────────────────────
        if isinstance(elem, Partition):
            label = elem.adjacent.strip()
            sig = _adjacent_signal_name(label) if label else "T_unknown"
            _add(("DirectLoss", sig), elem, [Channel.CONDUCTION])
            continue

    # ── Build DerivedModule list ───────────────────────────────────────────────
    derived: list[DerivedModule] = []

    # RoomMass first (mandatory)
    if room_mass_key in grouped:
        derived.append(DerivedModule(
            module=RoomMass(),
            elements=[],  # assembler auto-pairs IndoorMass; no elements passed here
            channels_claimed=[],
            key=room_mass_key,
        ))

    # Remaining modules in a stable order (sort keys for determinism)
    remaining_keys = [k for k in grouped if k != room_mass_key]
    remaining_keys.sort(key=lambda k: (k[0], k[1] or ""))

    for key in remaining_keys:
        type_name, sig_name = key
        entries = grouped[key]
        elems_for_module = [e for e, _ in entries]

        module = _make_module(type_name, sig_name)
        channels_for_module: list[Channel] = []
        seen_channels_for_key: set[Channel] = set()
        for _, chs in entries:
            for ch in chs:
                if ch not in seen_channels_for_key:
                    channels_for_module.append(ch)
                    seen_channels_for_key.add(ch)

        derived.append(DerivedModule(
            module=module,
            elements=elems_for_module,
            channels_claimed=channels_for_module,
            key=key,
        ))

    # ── Derive signals ────────────────────────────────────────────────────────
    signals = derive_signals(elements)

    return GroupResult(
        derived_modules=derived,
        signals=signals,
        _indoor_masses=indoor_masses,
    )


def _make_module(type_name: str, signal_name: str | None) -> TopologyModule:
    """Instantiate the TopologyModule for a given (type_name, signal_name) key."""
    if type_name == "RoomMass":
        return RoomMass()
    if type_name == "DirectLoss":
        return DirectLoss(T_bnd_signal=signal_name or "T_ext")
    if type_name == "SolarGain":
        return SolarGainModule(G_signal=signal_name or "G_sol")
    if type_name == "HeavyWall":
        return HeavyWall(T_bnd_signal=signal_name or "T_ext")
    if type_name == "SourceFlux":
        return SourceFluxModule(Q_signal=signal_name or "Q_prescribed")
    raise ValueError(f"Unknown module type name: {type_name!r}")
