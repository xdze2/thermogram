"""
Assembler: routes (element, channel) cells to modules, enforces exactly-once ownership,
builds the star ODE system.

Usage:
    asm = Assembler()
    asm.add_module(RoomMass(floor_area=20))
    asm.add_module(DirectLoss(), elements=[window])
    asm.add_module(HeavyWall(), elements=[wall])
    asm.add_module(SolarGainModule(), elements=[window])
    sys = asm.build()

Each element is explicitly routed to a module (or multiple modules for distinct channels).
The assembler then asserts exactly-once ownership per (element, channel) cell.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .channels import Budget, Channel
from .elements import EnvelopeElement
from .modules import RoomMass, TopologyModule

Params = dict[str, float]
Signals = dict[str, Any]


@dataclass
class Problem:
    """A structured assembly problem reported in non-raising mode."""

    kind: str        # double_count | unclaimed_channel | missing_room_mass | duplicate_state
    message: str
    cell: tuple[str, str] | None = None  # (element_label, channel_name) or None


@dataclass
class System:
    """Assembled star ODE system ready for forward simulation."""

    state_names: list[str]       # T_room is last by convention
    param_names: list[str]
    signal_names: list[str]
    priors: dict[str, tuple[float, float]]  # {param: (mu_log, sigma_log)}
    _modules: list[TopologyModule] = field(repr=False)
    _C_room_param: str = field(repr=False, default="C_room")
    # (element_type, channel) -> module_name; set by Assembler.build()
    _ownership: dict[tuple[str, "Channel"], str] = field(repr=False, default_factory=dict)
    # param_name -> [{element_label, channel, budget_field, value}]; set by Assembler.build()
    _contributions: dict[str, list[dict]] = field(repr=False, default_factory=dict)

    def ownership_map(self) -> dict[tuple[str, "Channel"], str]:
        """Return the (element_type, channel) -> module_name routing table."""
        return dict(self._ownership)

    def parameter_contributions(self) -> dict[str, list[dict]]:
        """
        Return which (element, channel) budgets fed each parameter's prior.
        Shape: {param_name: [{element_label, channel, budget_field, value}]}
        """
        return {k: list(v) for k, v in self._contributions.items()}

    def rhs(self, t: float, x: np.ndarray, signals: Signals, params: Params) -> np.ndarray:
        """
        Right-hand side of the ODE: dx/dt.
        x is ordered as state_names (T_room last).
        Signal values must already be scalars at time t.
        """
        states = dict(zip(self.state_names, x))
        C_room = params[self._C_room_param]

        dx = np.zeros(len(self.state_names))
        flux_sum = 0.0

        for mod in self._modules:
            flux_sum += mod.flux_room(params, signals, states)
            for sname, deriv in mod.state_ode(params, signals, states).items():
                dx[self.state_names.index(sname)] = deriv

        dx[-1] = flux_sum / C_room
        return dx


class Assembler:
    def __init__(self):
        self._room_mass: RoomMass | None = None
        # list of (module, [elements routed to it])
        self._routes: list[tuple[TopologyModule, list[EnvelopeElement]]] = []

    def add_module(
        self,
        module: TopologyModule,
        elements: list[EnvelopeElement] | None = None,
    ) -> "Assembler":
        """
        Register a module and, optionally, the elements whose channel budgets it spends.
        RoomMass takes no elements (it derives its prior from floor_area alone).
        """
        if isinstance(module, RoomMass):
            self._room_mass = module
        else:
            self._routes.append((module, list(elements or [])))
        return self

    def build(self, strict: bool = True) -> "System | tuple[System | None, list[Problem]]":
        """
        Assemble the system.

        strict=True (default): raise ValueError / emit warnings.warn on problems.
        strict=False: collect problems into a list and return (System | None, problems).
                      Returns None as the System when RoomMass is missing.
        """
        problems: list[Problem] = []

        def _problem(kind: str, message: str, cell: tuple[str, str] | None = None) -> None:
            if strict:
                if kind in ("double_count", "missing_room_mass", "duplicate_state"):
                    raise ValueError(message)
                else:
                    warnings.warn(message, stacklevel=3)
            else:
                problems.append(Problem(kind=kind, message=message, cell=cell))

        if self._room_mass is None:
            _problem("missing_room_mass", "RoomMass module is required.")
            if not strict:
                return None, problems
            # strict path already raised above

        # Step 1: compute (element_id, channel) → Budget for every routed element
        all_element_cells: dict[int, dict[Channel, Budget]] = {}
        elem_labels: dict[int, str] = {}
        elem_counter: dict[str, int] = {}
        for mod, elems in self._routes:
            for elem in elems:
                eid = id(elem)
                if eid not in all_element_cells:
                    all_element_cells[eid] = elem.channels()
                    base = type(elem).__name__
                    n = elem_counter.get(base, 0)
                    elem_labels[eid] = base if n == 0 else f"{base}_{n}"
                    elem_counter[base] = n + 1

        # Step 2: route; enforce exactly-once per (element_id, channel) cell
        ownership: dict[tuple[int, Channel], str] = {}
        module_cells: dict[str, dict[tuple[int, Channel], Budget]] = {
            mod.name: {} for mod, _ in self._routes
        }

        for mod, elems in self._routes:
            for elem in elems:
                eid = id(elem)
                label = elem_labels[eid]
                for ch, budget in all_element_cells[eid].items():
                    if ch not in mod.owns:
                        continue
                    cell_key = (eid, ch)
                    if cell_key in ownership:
                        _problem(
                            "double_count",
                            f"Double-count: (element {type(elem).__name__}, {ch}) "
                            f"already owned by '{ownership[cell_key]}', "
                            f"cannot also be owned by '{mod.name}'.",
                            cell=(label, ch.name),
                        )
                        # In non-strict mode keep first owner; skip re-registering.
                        continue
                    ownership[cell_key] = mod.name
                    module_cells[mod.name][cell_key] = budget

        # Unclaimed channels
        for eid, ch_map in all_element_cells.items():
            label = elem_labels[eid]
            for ch in ch_map:
                if (eid, ch) not in ownership:
                    _problem(
                        "unclaimed_channel",
                        f"Unclaimed channel {ch} on element '{label}'.",
                        cell=(label, ch.name),
                    )

        # Build human-readable ownership map: (element_label, channel) → module_name
        readable_ownership: dict[tuple[str, Channel], str] = {
            (elem_labels[eid], ch): mod_name
            for (eid, ch), mod_name in ownership.items()
        }

        # Step 3: collect state names (private states first, T_room last)
        private_states: list[str] = []
        for mod, _ in self._routes:
            for s in mod.private_states:
                if s in private_states:
                    _problem("duplicate_state", f"Duplicate private state name {s!r}.")
                    if not strict:
                        continue
                private_states.append(s)
        state_names = private_states + ["T_room"]

        # Step 4: collect param names
        all_params: list[str] = list(self._room_mass.params)
        for mod, _ in self._routes:
            for p in mod.params:
                if p not in all_params:
                    all_params.append(p)

        # Step 5: collect signal names
        all_signals: list[str] = []
        for mod, _ in self._routes:
            for s in mod.signals:
                if s not in all_signals:
                    all_signals.append(s)

        # Step 6: derive priors and build parameter contributions
        priors: dict[str, tuple[float, float]] = {}
        contributions: dict[str, list[dict]] = {}

        priors.update(self._room_mass.derive_priors({}))

        for mod, _ in self._routes:
            cells = module_cells[mod.name]
            priors.update(mod.derive_priors(cells))
            # Surface which (element, channel) budget fields fed each param's prior.
            _budget_fields = ("UA", "shgcA", "alphaA", "C")
            for param in mod.params:
                entries: list[dict] = []
                for (eid, ch), budget in cells.items():
                    for bf in _budget_fields:
                        val = getattr(budget, bf)
                        if val is not None:
                            entries.append({
                                "element_label": elem_labels[eid],
                                "channel": ch.name,
                                "budget_field": bf,
                                "value": val,
                            })
                if entries:
                    contributions.setdefault(param, []).extend(entries)

        all_mods: list[TopologyModule] = [self._room_mass] + [m for m, _ in self._routes]
        system = System(
            state_names=state_names,
            param_names=all_params,
            signal_names=all_signals,
            priors=priors,
            _modules=all_mods,
            _ownership=readable_ownership,
            _contributions=contributions,
        )

        if not strict:
            return system, problems
        return system
