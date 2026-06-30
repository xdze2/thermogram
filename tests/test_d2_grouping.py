"""
D2 acceptance tests — the grouping rule (spec 15 §"Grouping rule"; spec 40 I8).

These tests author each canonical room in plain Python through the new element
model (elements + boundaries + treatments), run the grouping rule, and assert
that the derived module set equals exactly what building physics dictates.

Canonical room table (from TODO.md §D5 / D2 acceptance):
┌────────────────────────────┬────────────────────────────────────────────────┬───────────────────────────────────────────────────────────────────┐
│ room                       │ authored                                       │ derived modules (must equal)                                      │
├────────────────────────────┼────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────┤
│ caravan (all-light)        │ light walls + S window + IndoorMass            │ RoomMass, DirectLoss[T_ext], SolarGain[G_sol_S]                   │
│ two adjacent rooms         │ + 2 partitions→kitchen, 1 partition→hallway   │ + DirectLoss[T_kitchen], DirectLoss[T_hallway]                    │
│ two glazing orientations   │ S window + W window                            │ SolarGain[G_sol_S], SolarGain[G_sol_W]  (two, not one)            │
│ heavy wall + treatment flip│ heavy S wall; toggle simple-loss               │ HeavyWall[T_ext] ↔ DirectLoss[T_ext]                             │
└────────────────────────────┴────────────────────────────────────────────────┴───────────────────────────────────────────────────────────────────┘

Additional tests:
- Two south windows collapse to ONE SolarGain[G_sol_S] (budgets summed).
- Signal liveness: deleting the last element referencing T_hallway GCs that signal.
- No problems on any clean room.
- Exactly-once assertion still fires on a constructed double-count.
- Build the assembled System from a grouped room and confirm forward_sim runs.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from thnodes import (
    Assembler,
    Floor,
    IndoorMass,
    Layer,
    OuterWall,
    Partition,
    Problem,
    Window,
    forward_sim,
    group,
    derive_signals,
)
from thnodes.channels import Channel
from thnodes.grouping import DerivedModule, GroupResult


# ── helpers ────────────────────────────────────────────────────────────────────

def _keys(result: GroupResult) -> set[tuple[str, str | None]]:
    """Return the set of (type_name, signal_name) keys from a GroupResult."""
    return {dm.key for dm in result.derived_modules}


def _signal_names(result: GroupResult) -> set[str]:
    return {s.name for s in result.signals}


def _prior_mean_params(system) -> dict:
    return {p: math.exp(mu) for p, (mu, _) in system.priors.items()}


_INSULATION = Layer("insulation_mineral_wool", 0.1)
_CONCRETE = Layer("concrete", 0.2)          # heavy (rho=2300)
_LIGHT_LAYER = Layer("insulation_mineral_wool", 0.1)  # light (rho=30)


def _light_wall(orientation: str = "N", area: float = 10.0) -> OuterWall:
    return OuterWall(area=area, orientation=orientation, layers=[_LIGHT_LAYER])


def _heavy_wall(orientation: str = "S", area: float = 10.0) -> OuterWall:
    return OuterWall(
        area=area,
        orientation=orientation,
        layers=[Layer("concrete", 0.2), _INSULATION],
    )


def _window(orientation: str = "S", area: float = 4.0) -> Window:
    return Window(area=area, orientation=orientation, U=1.2, shgc=0.6)


def _indoor_mass() -> IndoorMass:
    return IndoorMass(a=5.0, b=4.0, c=2.5, furniture="normal")


def _partition(room: str, area: float = 8.0) -> Partition:
    return Partition(
        area=area,
        layers=[_INSULATION],
        adjacent=room,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. Canonical room: caravan (all-light)
# ══════════════════════════════════════════════════════════════════════════════

class TestCaravanRoom:
    """
    Caravan room: IndoorMass + light walls + one south window.
    Expected: RoomMass, DirectLoss[T_ext], SolarGain[G_sol_S].
    """

    @pytest.fixture
    def caravan_elements(self):
        return [
            _indoor_mass(),
            _light_wall("N"),
            _light_wall("E"),
            _light_wall("W"),
            _window("S"),
        ]

    def test_caravan_derived_keys(self, caravan_elements):
        result = group(caravan_elements)
        expected = {
            ("RoomMass", None),
            ("DirectLoss", "T_ext"),
            ("SolarGain", "G_sol_S"),
        }
        assert _keys(result) == expected

    def test_caravan_exactly_three_modules(self, caravan_elements):
        result = group(caravan_elements)
        assert len(result.derived_modules) == 3

    def test_caravan_signals(self, caravan_elements):
        result = group(caravan_elements)
        assert "T_ext" in _signal_names(result)
        assert "G_sol_S" in _signal_names(result)
        # No adjacent or ground signals.
        assert "T_ground" not in _signal_names(result)

    def test_caravan_room_mass_first(self, caravan_elements):
        """RoomMass must be the first derived module (feeds the assembler first)."""
        result = group(caravan_elements)
        assert result.derived_modules[0].key == ("RoomMass", None)

    def test_caravan_no_problems_assembles(self, caravan_elements):
        result = group(caravan_elements)
        asm = result.to_assembler()
        system, problems = asm.build(strict=False)
        assert system is not None
        fatal = [p for p in problems if p.kind in ("double_count", "missing_room_mass")]
        assert fatal == [], f"Fatal problems: {fatal}"

    def test_caravan_forward_sim_runs(self, caravan_elements):
        """Build from grouping result and confirm forward_sim produces output."""
        result = group(caravan_elements)
        asm = result.to_assembler()
        system, _ = asm.build(strict=False)
        assert system is not None

        params = _prior_mean_params(system)
        n = 50
        sigs = {name: np.full(n, 5.0) for name in system.signal_names}
        x0 = np.full(len(system.state_names), 20.0)
        t_span = (0, (n - 1) * 3600.0)

        t, x = forward_sim(system, sigs, t_span, x0, params, dt=3600.0)
        assert t.shape[0] == n
        assert x.shape == (len(system.state_names), n)
        # T_room must be finite.
        assert np.all(np.isfinite(x[-1]))


# ══════════════════════════════════════════════════════════════════════════════
# 2. Canonical room: two adjacent rooms
# ══════════════════════════════════════════════════════════════════════════════

class TestAdjacentRooms:
    """
    Caravan + two partitions→kitchen + one partition→hallway.
    Expected additions: DirectLoss[T_kitchen], DirectLoss[T_hallway].
    """

    @pytest.fixture
    def adjacent_elements(self):
        return [
            _indoor_mass(),
            _light_wall("N"),
            _window("S"),
            _partition("kitchen"),
            _partition("kitchen"),  # second partition to same room
            _partition("hallway"),
        ]

    def test_adjacent_derived_keys(self, adjacent_elements):
        result = group(adjacent_elements)
        expected = {
            ("RoomMass", None),
            ("DirectLoss", "T_ext"),
            ("SolarGain", "G_sol_S"),
            ("DirectLoss", "T_kitchen"),
            ("DirectLoss", "T_hallway"),
        }
        assert _keys(result) == expected

    def test_kitchen_partitions_one_module(self, adjacent_elements):
        """Two partitions→kitchen must collapse to ONE DirectLoss[T_kitchen]."""
        result = group(adjacent_elements)
        kitchen_modules = [dm for dm in result.derived_modules if dm.key == ("DirectLoss", "T_kitchen")]
        assert len(kitchen_modules) == 1, "Two kitchen partitions must produce exactly one module"

    def test_kitchen_module_has_two_elements(self, adjacent_elements):
        """DirectLoss[T_kitchen] must claim both kitchen partitions."""
        result = group(adjacent_elements)
        dm = next(dm for dm in result.derived_modules if dm.key == ("DirectLoss", "T_kitchen"))
        assert len(dm.elements) == 2

    def test_hallway_is_separate_module(self, adjacent_elements):
        """Hallway partition must be a SEPARATE DirectLoss module from kitchen."""
        result = group(adjacent_elements)
        keys = _keys(result)
        assert ("DirectLoss", "T_kitchen") in keys
        assert ("DirectLoss", "T_hallway") in keys

    def test_adjacent_signals(self, adjacent_elements):
        result = group(adjacent_elements)
        names = _signal_names(result)
        assert "T_kitchen" in names
        assert "T_hallway" in names
        assert "T_ext" in names
        assert "G_sol_S" in names

    def test_adjacent_no_problems(self, adjacent_elements):
        result = group(adjacent_elements)
        asm = result.to_assembler()
        system, problems = asm.build(strict=False)
        assert system is not None
        fatal = [p for p in problems if p.kind in ("double_count", "missing_room_mass")]
        assert fatal == []

    def test_adjacent_forward_sim_runs(self, adjacent_elements):
        """forward_sim must handle a room with 3 DirectLoss modules."""
        result = group(adjacent_elements)
        asm = result.to_assembler()
        system, _ = asm.build(strict=False)
        assert system is not None

        params = _prior_mean_params(system)
        n = 50
        sigs = {name: np.full(n, 20.0) for name in system.signal_names}
        x0 = np.full(len(system.state_names), 20.0)
        t_span = (0, (n - 1) * 3600.0)

        t, x = forward_sim(system, sigs, t_span, x0, params, dt=3600.0)
        assert np.all(np.isfinite(x[-1]))


# ══════════════════════════════════════════════════════════════════════════════
# 3. Canonical room: two glazing orientations
# ══════════════════════════════════════════════════════════════════════════════

class TestTwoGlazingOrientations:
    """
    S window + W window → two SolarGain modules, NOT one.
    """

    @pytest.fixture
    def two_orient_elements(self):
        return [
            _indoor_mass(),
            _window("S"),
            _window("W"),
        ]

    def test_two_solar_modules(self, two_orient_elements):
        result = group(two_orient_elements)
        solar_keys = {k for k in _keys(result) if k[0] == "SolarGain"}
        assert solar_keys == {("SolarGain", "G_sol_S"), ("SolarGain", "G_sol_W")}, (
            f"Expected two SolarGain modules (S and W), got: {solar_keys}"
        )

    def test_two_solar_signals(self, two_orient_elements):
        result = group(two_orient_elements)
        names = _signal_names(result)
        assert "G_sol_S" in names
        assert "G_sol_W" in names

    def test_total_module_count(self, two_orient_elements):
        """RoomMass + DirectLoss[T_ext] (both windows cond.) + SolarGain[S] + SolarGain[W]."""
        result = group(two_orient_elements)
        assert _keys(result) == {
            ("RoomMass", None),
            ("DirectLoss", "T_ext"),
            ("SolarGain", "G_sol_S"),
            ("SolarGain", "G_sol_W"),
        }

    def test_two_orient_no_problems(self, two_orient_elements):
        result = group(two_orient_elements)
        asm = result.to_assembler()
        system, problems = asm.build(strict=False)
        assert system is not None
        fatal = [p for p in problems if p.kind in ("double_count", "missing_room_mass")]
        assert fatal == []

    def test_two_orient_forward_sim_runs(self, two_orient_elements):
        """forward_sim must work with two separate SolarGain modules."""
        result = group(two_orient_elements)
        asm = result.to_assembler()
        system, _ = asm.build(strict=False)
        assert system is not None

        params = _prior_mean_params(system)
        n = 50
        sigs = {name: np.full(n, 200.0) for name in system.signal_names}
        # Temperature signals should be realistic (20°C), not 200 W/m²
        for sname in system.signal_names:
            if sname.startswith("T_"):
                sigs[sname] = np.full(n, 20.0)
        x0 = np.full(len(system.state_names), 20.0)
        t_span = (0, (n - 1) * 3600.0)

        t, x = forward_sim(system, sigs, t_span, x0, params, dt=3600.0)
        assert np.all(np.isfinite(x[-1]))


# ══════════════════════════════════════════════════════════════════════════════
# 4. Canonical room: heavy wall + treatment flip
# ══════════════════════════════════════════════════════════════════════════════

class TestHeavyWallTreatmentFlip:
    """
    Heavy south wall: treatment="" (default) → HeavyWall[T_ext].
    treatment="simple_loss"               → DirectLoss[T_ext] (no HeavyWall).
    """

    def test_heavy_wall_default_treatment(self):
        heavy = _heavy_wall("S")
        assert heavy.treatment == ""
        result = group([_indoor_mass(), heavy])
        keys = _keys(result)
        assert ("HeavyWall", "T_ext") in keys, f"Expected HeavyWall[T_ext] in {keys}"
        assert ("DirectLoss", "T_ext") not in keys, "HeavyWall should not coexist with DirectLoss[T_ext]"

    def test_heavy_wall_thermal_mass_treatment(self):
        """Explicit thermal_mass treatment is the same as the default."""
        heavy = OuterWall(
            area=10.0,
            orientation="S",
            layers=[Layer("concrete", 0.2), _INSULATION],
            treatment="thermal_mass",
        )
        result = group([_indoor_mass(), heavy])
        keys = _keys(result)
        assert ("HeavyWall", "T_ext") in keys

    def test_heavy_wall_simple_loss_treatment(self):
        heavy = OuterWall(
            area=10.0,
            orientation="S",
            layers=[Layer("concrete", 0.2), _INSULATION],
            treatment="simple_loss",
        )
        result = group([_indoor_mass(), heavy])
        keys = _keys(result)
        assert ("DirectLoss", "T_ext") in keys, f"Expected DirectLoss[T_ext] in {keys}"
        assert ("HeavyWall", "T_ext") not in keys, "simple_loss override must suppress HeavyWall"

    def test_treatment_flip_swaps_module(self):
        """Toggling treatment is the ONLY change; module identity flips accordingly."""
        heavy_default = _heavy_wall("S")
        heavy_simple = OuterWall(
            area=10.0,
            orientation="S",
            layers=[Layer("concrete", 0.2), _INSULATION],
            treatment="simple_loss",
        )
        keys_default = _keys(group([_indoor_mass(), heavy_default]))
        keys_simple = _keys(group([_indoor_mass(), heavy_simple]))

        assert ("HeavyWall", "T_ext") in keys_default
        assert ("HeavyWall", "T_ext") not in keys_simple
        assert ("DirectLoss", "T_ext") in keys_simple
        assert ("DirectLoss", "T_ext") not in keys_default

    def test_light_wall_forced_to_direct_loss(self):
        """A light wall is always DirectLoss regardless of treatment field."""
        light = _light_wall("N")
        result = group([_indoor_mass(), light])
        keys = _keys(result)
        assert ("DirectLoss", "T_ext") in keys
        assert ("HeavyWall", "T_ext") not in keys

    def test_heavy_default_no_problems(self):
        result = group([_indoor_mass(), _heavy_wall("S"), _window("S")])
        asm = result.to_assembler()
        system, problems = asm.build(strict=False)
        assert system is not None
        fatal = [p for p in problems if p.kind in ("double_count", "missing_room_mass")]
        assert fatal == []

    def test_heavy_simple_loss_no_problems(self):
        heavy = OuterWall(
            area=10.0,
            orientation="S",
            layers=[Layer("concrete", 0.2), _INSULATION],
            treatment="simple_loss",
        )
        result = group([_indoor_mass(), heavy, _window("S")])
        asm = result.to_assembler()
        system, problems = asm.build(strict=False)
        assert system is not None
        fatal = [p for p in problems if p.kind in ("double_count", "missing_room_mass")]
        assert fatal == []

    def test_heavy_wall_forward_sim_runs(self):
        """HeavyWall produces a 2-state system; forward_sim must succeed."""
        result = group([_indoor_mass(), _heavy_wall("S")])
        asm = result.to_assembler()
        system, _ = asm.build(strict=False)
        assert system is not None
        assert "T_wall" in system.state_names, "HeavyWall must add T_wall private state"

        params = _prior_mean_params(system)
        n = 50
        sigs = {name: np.full(n, 10.0) for name in system.signal_names}
        x0 = np.full(len(system.state_names), 20.0)
        t_span = (0, (n - 1) * 3600.0)

        t, x = forward_sim(system, sigs, t_span, x0, params, dt=3600.0)
        assert np.all(np.isfinite(x[-1]))


# ══════════════════════════════════════════════════════════════════════════════
# 5. Budget summation — two south windows collapse to one SolarGain[G_sol_S]
# ══════════════════════════════════════════════════════════════════════════════

class TestBudgetSummation:
    """
    Two south windows must collapse to ONE SolarGain[G_sol_S] with the
    combined (summed) shgcA budget as the prior mean.
    """

    def test_two_south_windows_one_solar_module(self):
        win1 = Window(area=4.0, orientation="S", U=1.2, shgc=0.6)
        win2 = Window(area=2.0, orientation="S", U=1.4, shgc=0.5)
        result = group([_indoor_mass(), win1, win2])

        solar_modules = [dm for dm in result.derived_modules if dm.key == ("SolarGain", "G_sol_S")]
        assert len(solar_modules) == 1, "Two south windows must yield exactly one SolarGain[G_sol_S]"

    def test_two_south_windows_summed_shgca(self):
        """Prior mean of shgcA must equal sum of both windows' shgcA budgets."""
        win1 = Window(area=4.0, orientation="S", U=1.2, shgc=0.6)
        win2 = Window(area=2.0, orientation="S", U=1.4, shgc=0.5)
        result = group([_indoor_mass(), win1, win2])
        asm = result.to_assembler()
        system, _ = asm.build(strict=False)
        assert system is not None

        expected_shgcA = win1.shgc * win1.area + win2.shgc * win2.area
        # The shgcA param name for the default G_sol signal is "shgcA";
        # for "G_sol_S" it is "shgcA_G_sol_S" (non-default signal).
        shgca_param = next(p for p in system.param_names if p.startswith("shgcA"))
        prior_mean = math.exp(system.priors[shgca_param][0])
        assert prior_mean == pytest.approx(expected_shgcA, rel=1e-6)

    def test_two_south_windows_two_elements_in_module(self):
        """The single SolarGain[G_sol_S] DerivedModule must carry both elements."""
        win1 = Window(area=4.0, orientation="S", U=1.2, shgc=0.6)
        win2 = Window(area=2.0, orientation="S", U=1.4, shgc=0.5)
        result = group([_indoor_mass(), win1, win2])
        dm = next(dm for dm in result.derived_modules if dm.key == ("SolarGain", "G_sol_S"))
        assert len(dm.elements) == 2

    def test_two_south_windows_conduction_also_summed(self):
        """The DirectLoss[T_ext] conduction prior must sum both windows' UA."""
        win1 = Window(area=4.0, orientation="S", U=1.2, shgc=0.6)
        win2 = Window(area=2.0, orientation="S", U=1.4, shgc=0.5)
        result = group([_indoor_mass(), win1, win2])
        asm = result.to_assembler()
        system, _ = asm.build(strict=False)
        assert system is not None

        expected_UA = win1.U * win1.area + win2.U * win2.area
        prior_mean = math.exp(system.priors["H_ve"][0])
        assert prior_mean == pytest.approx(expected_UA, rel=1e-6)

    def test_three_windows_different_orientations(self):
        """S + S + W → two SolarGain modules (not three)."""
        win_s1 = Window(area=2.0, orientation="S", U=1.2, shgc=0.6)
        win_s2 = Window(area=1.0, orientation="S", U=1.2, shgc=0.6)
        win_w = Window(area=3.0, orientation="W", U=1.2, shgc=0.6)
        result = group([_indoor_mass(), win_s1, win_s2, win_w])
        solar_keys = {k for k in _keys(result) if k[0] == "SolarGain"}
        assert solar_keys == {("SolarGain", "G_sol_S"), ("SolarGain", "G_sol_W")}


# ══════════════════════════════════════════════════════════════════════════════
# 6. Signal liveness invariant
# ══════════════════════════════════════════════════════════════════════════════

class TestSignalLiveness:
    """
    derive_signals returns only signals referenced by at least one element.
    Removing the last element that references a signal GCs that signal.
    """

    def test_liveness_hallway_signal_gc(self):
        """
        With a hallway partition: T_hallway signal exists.
        Without it: T_hallway must not appear (garbage-collected).
        """
        elements_with = [_indoor_mass(), _partition("hallway")]
        elements_without = [_indoor_mass(), _partition("kitchen")]

        sigs_with = derive_signals(elements_with)
        sigs_without = derive_signals(elements_without)

        names_with = {s.name for s in sigs_with}
        names_without = {s.name for s in sigs_without}

        assert "T_hallway" in names_with
        assert "T_hallway" not in names_without, (
            "T_hallway must be GC'd when no element references it"
        )

    def test_liveness_solar_gc(self):
        """Removing the west window GCs G_sol_W."""
        elems_both = [_indoor_mass(), _window("S"), _window("W")]
        elems_s_only = [_indoor_mass(), _window("S")]

        names_both = {s.name for s in derive_signals(elems_both)}
        names_s_only = {s.name for s in derive_signals(elems_s_only)}

        assert "G_sol_W" in names_both
        assert "G_sol_W" not in names_s_only

    def test_liveness_exterior_gc(self):
        """IndoorMass alone needs no exterior signal."""
        sigs = derive_signals([_indoor_mass()])
        assert not sigs, f"IndoorMass alone must produce no signals, got: {sigs}"

    def test_liveness_ground_gc(self):
        """A ground-boundary floor adds T_ground; an exposed floor adds T_ext, not T_ground."""
        ground_floor = Floor(
            area=20.0,
            boundary="ground",
            layers=[_CONCRETE],
        )
        exposed_floor = Floor(
            area=20.0,
            boundary="exposed",
            layers=[_CONCRETE],
        )

        names_ground = {s.name for s in derive_signals([ground_floor])}
        names_exposed = {s.name for s in derive_signals([exposed_floor])}

        assert "T_ground" in names_ground
        assert "T_ground" not in names_exposed
        assert "T_ext" in names_exposed
        assert "T_ext" not in names_ground

    def test_liveness_prescribed_not_auto_created(self):
        """
        Prescribed signals (HVAC, occupancy) are author-created only.
        derive_signals() must NOT auto-create them from a HeatSource element.
        """
        from thnodes import HeatSource
        sigs = derive_signals([_indoor_mass(), HeatSource()])
        roles = {s.role for s in sigs}
        assert "prescribed" not in roles, "HeatSource must not auto-create a prescribed signal"

    def test_signal_roles_correct(self):
        """Each auto-created signal has the correct role."""
        elements = [
            _indoor_mass(),
            _window("S"),
            _partition("kitchen"),
            Floor(area=20.0, boundary="ground", layers=[_CONCRETE]),
        ]
        sigs = {s.name: s for s in derive_signals(elements)}

        assert sigs["T_ext"].role == "exterior"
        assert sigs["T_ext"].kind == "temperature"
        assert sigs["G_sol_S"].role == "solar"
        assert sigs["G_sol_S"].kind == "irradiance"
        assert sigs["T_kitchen"].role == "adjacent"
        assert sigs["T_kitchen"].kind == "temperature"
        assert sigs["T_ground"].role == "ground"
        assert sigs["T_ground"].kind == "temperature"

    def test_solar_signal_orientation_in_meta(self):
        """Solar signal meta must carry the orientation."""
        sigs = {s.name: s for s in derive_signals([_window("SE")])}
        assert "G_sol_SE" in sigs
        assert sigs["G_sol_SE"].meta.get("orientation") == "SE"

    def test_adjacent_signal_room_in_meta(self):
        """Adjacent signal meta must carry the room label."""
        sigs = {s.name: s for s in derive_signals([_partition("cellar")])}
        assert "T_cellar" in sigs
        assert sigs["T_cellar"].meta.get("room") == "cellar"


# ══════════════════════════════════════════════════════════════════════════════
# 7. Exactly-once / double-count — engine bug detection still works
# ══════════════════════════════════════════════════════════════════════════════

class TestExactlyOnce:
    """
    The exactly-once (I3) check must still fire on a manually-constructed
    double-count (an engine bug scenario, not user error in the grouping path).
    """

    def test_manual_double_count_raises_strict(self):
        """Manually routing the same element to two modules that both claim CONDUCTION raises."""
        from thnodes import DirectLoss, HeavyWall, RoomMass

        heavy = _heavy_wall("S")
        indoor = _indoor_mass()
        asm = Assembler()
        asm.add_element(indoor)
        asm.add_module(RoomMass())
        asm.add_module(DirectLoss(), elements=[heavy])   # claims CONDUCTION
        asm.add_module(HeavyWall(), elements=[heavy])    # also claims CONDUCTION → double-count
        with pytest.raises(ValueError, match="[Dd]ouble"):
            asm.build(strict=True)

    def test_manual_double_count_problem_non_strict(self):
        """In non-strict mode a double-count yields a Problem, not an exception."""
        from thnodes import DirectLoss, HeavyWall, RoomMass

        heavy = _heavy_wall("S")
        indoor = _indoor_mass()
        asm = Assembler()
        asm.add_element(indoor)
        asm.add_module(RoomMass())
        asm.add_module(DirectLoss(), elements=[heavy])
        asm.add_module(HeavyWall(), elements=[heavy])
        system, problems = asm.build(strict=False)
        kinds = {p.kind for p in problems}
        assert "double_count" in kinds

    def test_grouping_rule_produces_no_double_count(self):
        """
        The grouping rule itself must never produce a double-count on any
        valid element set (clean-room invariant).
        """
        elements = [
            _indoor_mass(),
            _light_wall("N"),
            _light_wall("E"),
            _heavy_wall("S"),
            _window("S"),
            _window("W"),
            _partition("kitchen"),
            _partition("kitchen"),
            _partition("hallway"),
            Floor(area=20.0, boundary="ground", layers=[_CONCRETE]),
        ]
        result = group(elements)
        asm = result.to_assembler()
        system, problems = asm.build(strict=False)
        double_counts = [p for p in problems if p.kind == "double_count"]
        assert double_counts == [], (
            f"Grouping rule produced double-counts (engine bug): {double_counts}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 8. Floor routing
# ══════════════════════════════════════════════════════════════════════════════

class TestFloorRouting:
    """
    Floors route differently depending on their boundary field.
    """

    def test_ground_floor(self):
        floor = Floor(area=20.0, boundary="ground", layers=[_CONCRETE])
        result = group([_indoor_mass(), floor])
        assert ("DirectLoss", "T_ground") in _keys(result)

    def test_exposed_floor(self):
        floor = Floor(area=20.0, boundary="exposed", layers=[_CONCRETE])
        result = group([_indoor_mass(), floor])
        assert ("DirectLoss", "T_ext") in _keys(result)

    def test_adjacent_floor(self):
        floor = Floor(area=20.0, boundary="adjacent", layers=[_CONCRETE], adjacent_room="garage")
        result = group([_indoor_mass(), floor])
        assert ("DirectLoss", "T_garage") in _keys(result)

    def test_adjacent_floor_signal_name(self):
        floor = Floor(area=20.0, boundary="adjacent", layers=[_CONCRETE], adjacent_room="basement")
        sigs = {s.name for s in derive_signals([floor])}
        assert "T_basement" in sigs

    def test_ground_floor_no_problems(self):
        floor = Floor(area=20.0, boundary="ground", layers=[_CONCRETE])
        result = group([_indoor_mass(), floor])
        asm = result.to_assembler()
        system, problems = asm.build(strict=False)
        assert system is not None
        fatal = [p for p in problems if p.kind in ("double_count", "missing_room_mass")]
        assert fatal == []

    def test_ground_floor_forward_sim(self):
        """forward_sim with a ground floor (DirectLoss[T_ground]) must succeed."""
        floor = Floor(area=20.0, boundary="ground", layers=[_CONCRETE])
        result = group([_indoor_mass(), floor])
        asm = result.to_assembler()
        system, _ = asm.build(strict=False)
        assert system is not None

        params = _prior_mean_params(system)
        n = 50
        sigs = {name: np.full(n, 10.0) for name in system.signal_names}
        x0 = np.full(len(system.state_names), 20.0)
        t_span = (0, (n - 1) * 3600.0)

        t, x = forward_sim(system, sigs, t_span, x0, params, dt=3600.0)
        assert np.all(np.isfinite(x[-1]))


# ══════════════════════════════════════════════════════════════════════════════
# 9. Module parametric-signal attributes
# ══════════════════════════════════════════════════════════════════════════════

class TestModuleParametricSignal:
    """
    DirectLoss, SolarGainModule, HeavyWall must expose their boundary signal
    in the ``signal`` attribute and must produce distinct param names when
    instantiated with non-default signals.
    """

    def test_direct_loss_default_signal(self):
        from thnodes import DirectLoss
        m = DirectLoss()
        assert m.signal == "T_ext"
        assert "T_ext" in m.signals
        assert "H_ve" in m.params

    def test_direct_loss_custom_signal(self):
        from thnodes import DirectLoss
        m = DirectLoss("T_kitchen")
        assert m.signal == "T_kitchen"
        assert "T_kitchen" in m.signals
        # Param must be suffixed to avoid collision.
        assert any("T_kitchen" in p for p in m.params), (
            f"Expected T_kitchen in param names, got {m.params}"
        )

    def test_solar_gain_default_signal(self):
        from thnodes import SolarGainModule
        m = SolarGainModule()
        assert m.signal == "G_sol"
        assert "G_sol" in m.signals
        assert "shgcA" in m.params

    def test_solar_gain_custom_signal(self):
        from thnodes import SolarGainModule
        m = SolarGainModule("G_sol_W")
        assert m.signal == "G_sol_W"
        assert "G_sol_W" in m.signals
        assert any("G_sol_W" in p for p in m.params), (
            f"Expected G_sol_W in param names, got {m.params}"
        )

    def test_heavy_wall_default_signal(self):
        from thnodes import HeavyWall
        m = HeavyWall()
        assert m.signal == "T_ext"

    def test_heavy_wall_custom_signal(self):
        from thnodes import HeavyWall
        m = HeavyWall("T_ext_north")
        assert m.signal == "T_ext_north"

    def test_room_mass_signal_none(self):
        from thnodes import RoomMass
        m = RoomMass()
        assert m.signal is None

    def test_two_direct_loss_distinct_params(self):
        """
        Two DirectLoss modules with different signals must have distinct param names
        so the assembler can hold both priors simultaneously.
        """
        from thnodes import DirectLoss
        m1 = DirectLoss("T_ext")
        m2 = DirectLoss("T_kitchen")
        assert m1.params[0] != m2.params[0], (
            "DirectLoss[T_ext] and DirectLoss[T_kitchen] must have distinct param names"
        )

    def test_two_solar_gain_distinct_params(self):
        """Two SolarGainModule instances with different signals must have distinct param names."""
        from thnodes import SolarGainModule
        m_s = SolarGainModule("G_sol_S")
        m_w = SolarGainModule("G_sol_W")
        assert m_s.params[0] != m_w.params[0], (
            "SolarGain[G_sol_S] and SolarGain[G_sol_W] must have distinct param names"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 10. GroupResult.to_assembler + existing API compatibility
# ══════════════════════════════════════════════════════════════════════════════

class TestGroupResultToAssembler:
    """
    to_assembler() wires the Assembler correctly, and the resulting System
    matches expectations.
    """

    def test_room_mass_is_present(self):
        result = group([_indoor_mass(), _window("S")])
        asm = result.to_assembler()
        system, problems = asm.build(strict=False)
        assert system is not None
        assert "missing_room_mass" not in {p.kind for p in problems}

    def test_state_names_t_room_last(self):
        """By assembler convention T_room is last in state_names."""
        result = group([_indoor_mass(), _window("S")])
        asm = result.to_assembler()
        system, _ = asm.build(strict=False)
        assert system.state_names[-1] == "T_room"

    def test_heavy_wall_state_names(self):
        """HeavyWall adds T_wall; state_names must be [T_wall, T_room]."""
        result = group([_indoor_mass(), _heavy_wall("S")])
        asm = result.to_assembler()
        system, _ = asm.build(strict=False)
        assert system is not None
        assert "T_wall" in system.state_names
        assert system.state_names[-1] == "T_room"

    def test_priors_contain_all_params(self):
        """All param_names must appear in priors."""
        result = group([_indoor_mass(), _window("S"), _partition("kitchen")])
        asm = result.to_assembler()
        system, _ = asm.build(strict=False)
        assert system is not None
        for p in system.param_names:
            assert p in system.priors, f"Param {p!r} missing from priors"

    def test_signal_names_match_derived_signals(self):
        """All signal names in the System must correspond to a derived signal."""
        elements = [_indoor_mass(), _window("S"), _partition("kitchen")]
        result = group(elements)
        asm = result.to_assembler()
        system, _ = asm.build(strict=False)
        assert system is not None

        derived_names = {s.name for s in result.signals}
        for sname in system.signal_names:
            assert sname in derived_names, (
                f"System signal {sname!r} not in derived signal set {derived_names}"
            )

    def test_existing_direct_loss_default_unchanged(self):
        """
        DirectLoss() (no args) must still produce 'H_ve' param and 'T_ext' signal,
        unchanged from D1 / Step 0 behaviour.
        """
        from thnodes import DirectLoss, RoomMass
        indoor = _indoor_mass()
        wall = _light_wall()
        asm = Assembler()
        asm.add_element(indoor)
        asm.add_module(RoomMass())
        asm.add_module(DirectLoss(), elements=[wall])
        system = asm.build(strict=True)
        assert "H_ve" in system.param_names
        assert "T_ext" in system.signal_names

    def test_existing_solar_gain_default_unchanged(self):
        """
        SolarGainModule() (no args) must still produce 'shgcA' param and 'G_sol' signal,
        unchanged from D1 / Step 0 behaviour.

        The CONDUCTION channel of the Window is intentionally unclaimed here
        (we're testing SolarGainModule in isolation); the resulting warning is
        expected and suppressed.
        """
        import warnings
        from thnodes import RoomMass, SolarGainModule
        indoor = _indoor_mass()
        win = _window("S")
        asm = Assembler()
        asm.add_element(indoor)
        asm.add_module(RoomMass())
        asm.add_module(SolarGainModule(), elements=[win])
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*[Uu]nclaimed.*")
            system = asm.build(strict=True)
        assert "shgcA" in system.param_names
        assert "G_sol" in system.signal_names


# ══════════════════════════════════════════════════════════════════════════════
# 11. DerivedModule structure
# ══════════════════════════════════════════════════════════════════════════════

class TestDerivedModuleStructure:
    """
    DerivedModule must carry the correct (type_name, signal_name) key and have
    consistent channel_claimed values.
    """

    def test_derived_module_key_properties(self):
        result = group([_indoor_mass(), _window("S")])
        for dm in result.derived_modules:
            assert dm.type_name == dm.key[0]
            assert dm.signal_name == dm.key[1]

    def test_room_mass_no_elements(self):
        """RoomMass DerivedModule must have no elements (assembler auto-pairs IndoorMass)."""
        result = group([_indoor_mass()])
        rm = next(dm for dm in result.derived_modules if dm.key == ("RoomMass", None))
        assert rm.elements == []

    def test_indoor_mass_on_group_result(self):
        """GroupResult must expose the IndoorMass element for to_assembler()."""
        im = _indoor_mass()
        result = group([im, _window("S")])
        # _indoor_masses carries all IndoorMass elements (used internally by to_assembler)
        assert im in result._indoor_masses

    def test_heavy_wall_channels_claimed(self):
        """HeavyWall DerivedModule must claim CONDUCTION, STORAGE, SOLAR_OPAQUE."""
        from thnodes.channels import Channel
        result = group([_indoor_mass(), _heavy_wall("S")])
        dm = next(dm for dm in result.derived_modules if dm.type_name == "HeavyWall")
        claimed = set(dm.channels_claimed)
        assert Channel.CONDUCTION in claimed
        assert Channel.STORAGE in claimed
        assert Channel.SOLAR_OPAQUE in claimed

    def test_direct_loss_channels_claimed(self):
        """DirectLoss DerivedModule must claim only CONDUCTION."""
        from thnodes.channels import Channel
        result = group([_indoor_mass(), _light_wall("N")])
        dm = next(dm for dm in result.derived_modules if dm.type_name == "DirectLoss")
        assert dm.channels_claimed == [Channel.CONDUCTION]

    def test_solar_gain_channels_claimed(self):
        """SolarGain DerivedModule must claim only SOLAR_TRANSMISSION."""
        from thnodes.channels import Channel
        result = group([_indoor_mass(), _window("S")])
        dm = next(dm for dm in result.derived_modules if dm.type_name == "SolarGain")
        assert dm.channels_claimed == [Channel.SOLAR_TRANSMISSION]

    def test_groupresult_signal_names_no_duplicates(self):
        """derive_signals must never return two signals with the same name."""
        elements = [
            _indoor_mass(),
            _window("S"),
            _window("S"),  # two south windows; only one G_sol_S signal
            _partition("kitchen"),
            _partition("kitchen"),  # two partitions to kitchen; only one T_kitchen
        ]
        sigs = derive_signals(elements)
        names = [s.name for s in sigs]
        assert len(names) == len(set(names)), f"Duplicate signal names: {names}"


# ══════════════════════════════════════════════════════════════════════════════
# 12. Full integration: caravan via group() matches caravan via manual assembly
# ══════════════════════════════════════════════════════════════════════════════

class TestGroupedVsManualCaravan:
    """
    A caravan built via group() must produce the same param and state set as
    one built manually through the old Assembler.add_module() API (Step 0).
    The forward_sim results must be close (same priors → same prior-mean params).
    """

    def _manual_caravan(self):
        from thnodes import DirectLoss, RoomMass, SolarGainModule
        indoor = _indoor_mass()
        wall = _light_wall("N")
        win = _window("S")
        asm = Assembler()
        asm.add_element(indoor)
        asm.add_module(RoomMass())
        asm.add_module(DirectLoss(), elements=[wall, win])
        asm.add_module(SolarGainModule(), elements=[win])
        return asm.build(strict=True)

    def _grouped_caravan(self):
        elements = [_indoor_mass(), _light_wall("N"), _window("S")]
        result = group(elements)
        asm = result.to_assembler()
        system, _ = asm.build(strict=False)
        return system

    def test_same_state_names(self):
        manual = self._manual_caravan()
        grouped = self._grouped_caravan()
        assert set(manual.state_names) == set(grouped.state_names)

    def test_grouped_has_all_manual_params(self):
        """Grouped caravan must include 'C_room', 'H_ve', and a shgcA param."""
        grouped = self._grouped_caravan()
        assert "C_room" in grouped.param_names
        assert "H_ve" in grouped.param_names
        # SolarGain for non-default signal uses suffixed param; check any shgcA present.
        assert any(p.startswith("shgcA") for p in grouped.param_names)

    def test_grouped_no_problems(self):
        grouped = self._grouped_caravan()
        assert grouped is not None

    def test_grouped_forward_sim_stable(self):
        """Grouped caravan forward_sim must produce a stable trajectory."""
        sys_g = self._grouped_caravan()
        params = _prior_mean_params(sys_g)
        n = 100
        # Temperature signals at 20°C, irradiance signals at 0 W/m² (no solar gain).
        sigs = {}
        for name in sys_g.signal_names:
            if name.startswith("G_"):
                sigs[name] = np.zeros(n)
            else:
                sigs[name] = np.full(n, 20.0)
        x0 = np.array([15.0])
        t_span = (0, (n - 1) * 3600.0)

        t, x = forward_sim(sys_g, sigs, t_span, x0, params, dt=3600.0)
        T_room = x[-1]
        # Must converge toward 20°C (T_ext) from initial 15°C.
        assert T_room[-1] > T_room[0], "T_room should rise toward T_ext"
        assert T_room[-1] < 20.5, "T_room should not overshoot T_ext"
        assert np.all(np.isfinite(T_room))


# ══════════════════════════════════════════════════════════════════════════════
# 13. Heavy ground-floor slab: STORAGE is surfaced, never silent
# ══════════════════════════════════════════════════════════════════════════════

class TestHeavyGroundFloorStorage:
    """
    A Floor(boundary="ground") with a concrete layer is heavy — it carries a
    STORAGE budget.  The grouping rule only claims CONDUCTION (routes to
    DirectLoss[T_ground]); the STORAGE budget is unclaimed.  The assembler must
    surface this as an explicit, actionable problem — never silently drop it.
    """

    @pytest.fixture
    def elements_with_heavy_floor(self):
        return [
            _indoor_mass(),
            Floor(area=20.0, boundary="ground", layers=[_CONCRETE]),
        ]

    def test_heavy_ground_floor_surfaces_unclaimed_storage(self, elements_with_heavy_floor):
        """An unclaimed_channel problem is reported for the STORAGE budget."""
        result = group(elements_with_heavy_floor)
        asm = result.to_assembler()
        system, problems = asm.build(strict=False)
        assert system is not None, "assembly should still succeed (non-fatal problem)"

        storage_probs = [
            p for p in problems
            if p.kind == "unclaimed_channel" and p.cell is not None and p.cell[1] == "STORAGE"
        ]
        assert storage_probs, (
            "Expected an unclaimed_channel/STORAGE problem for the heavy ground floor; "
            f"got problems: {problems}"
        )

    def test_heavy_ground_floor_problem_message_is_actionable(self, elements_with_heavy_floor):
        """The problem message must mention 'slab', 'deferred', or 'not yet modelled'."""
        result = group(elements_with_heavy_floor)
        asm = result.to_assembler()
        _, problems = asm.build(strict=False)

        storage_probs = [
            p for p in problems
            if p.kind == "unclaimed_channel" and p.cell is not None and p.cell[1] == "STORAGE"
        ]
        assert storage_probs
        msg = storage_probs[0].message.lower()
        assert "deferred" in msg or "not yet modelled" in msg, (
            f"Message should explain that the slab mass is a known deferred feature; got: {msg!r}"
        )
        assert "floor" in msg or "slab" in msg, (
            f"Message should identify the element as a floor/slab; got: {msg!r}"
        )

    def test_heavy_ground_floor_no_fatal_problems(self, elements_with_heavy_floor):
        """The STORAGE problem is non-fatal — double_count and missing_room_mass must be absent."""
        result = group(elements_with_heavy_floor)
        asm = result.to_assembler()
        system, problems = asm.build(strict=False)
        fatal = [p for p in problems if p.kind in ("double_count", "missing_room_mass")]
        assert fatal == []
        assert system is not None

    def test_light_ground_floor_no_storage_problem(self):
        """A light floor (insulation only, no STORAGE budget) produces no unclaimed_channel."""
        light_floor = Floor(area=20.0, boundary="ground", layers=[_LIGHT_LAYER])
        result = group([_indoor_mass(), light_floor])
        asm = result.to_assembler()
        _, problems = asm.build(strict=False)
        unclaimed = [p for p in problems if p.kind == "unclaimed_channel"]
        assert unclaimed == [], f"Light floor should have no unclaimed channels; got: {unclaimed}"

    def test_heavy_ground_floor_forward_sim_still_runs(self, elements_with_heavy_floor):
        """Assembly with an unclaimed STORAGE still produces a runnable system."""
        result = group(elements_with_heavy_floor)
        asm = result.to_assembler()
        system, _ = asm.build(strict=False)
        assert system is not None

        params = _prior_mean_params(system)
        n = 50
        sigs = {name: np.full(n, 10.0) for name in system.signal_names}
        x0 = np.full(len(system.state_names), 20.0)
        t_span = (0, (n - 1) * 3600.0)

        t, x = forward_sim(system, sigs, t_span, x0, params, dt=3600.0)
        assert np.all(np.isfinite(x[-1]))


# ══════════════════════════════════════════════════════════════════════════════
# 14. Multiple IndoorMass: surfaced as a problem, never silent
# ══════════════════════════════════════════════════════════════════════════════

class TestMultipleIndoorMass:
    """
    Only one room node (C_room) is supported.  Authoring two or more IndoorMass
    elements must produce a multiple_room_mass problem — not silently drop the
    extra capacity.  The assembler should still assemble using the first element.
    """

    @pytest.fixture
    def two_mass_elements(self):
        return [
            _indoor_mass(),                                    # 5×4×2.5, C ≈ 180900 J/K
            IndoorMass(a=3, b=4, c=2.5, furniture="normal"),  # 3×4×2.5, C ≈ 108540 J/K
            _window("S"),
        ]

    def test_two_indoor_mass_emits_problem(self, two_mass_elements):
        """Two IndoorMass elements yield a multiple_room_mass problem in non-strict mode."""
        result = group(two_mass_elements)
        asm = result.to_assembler()
        system, problems = asm.build(strict=False)

        mm_probs = [p for p in problems if p.kind == "multiple_room_mass"]
        assert mm_probs, (
            f"Expected a multiple_room_mass problem; got problems: {problems}"
        )

    def test_two_indoor_mass_problem_message_informative(self, two_mass_elements):
        """The problem message must state the count and explain the limitation."""
        result = group(two_mass_elements)
        asm = result.to_assembler()
        _, problems = asm.build(strict=False)

        mm_probs = [p for p in problems if p.kind == "multiple_room_mass"]
        assert mm_probs
        msg = mm_probs[0].message
        assert "2" in msg, f"Message should state count '2'; got: {msg!r}"
        assert "one" in msg.lower() or "single" in msg.lower(), (
            f"Message should state only one node is supported; got: {msg!r}"
        )

    def test_two_indoor_mass_nonstrict_still_assembles(self, two_mass_elements):
        """In non-strict mode the assembly succeeds despite the problem."""
        result = group(two_mass_elements)
        asm = result.to_assembler()
        system, problems = asm.build(strict=False)
        assert system is not None

    def test_two_indoor_mass_uses_first_element(self, two_mass_elements):
        """C_room must reflect only the first IndoorMass, not both summed."""
        import math

        first_mass = two_mass_elements[0]  # a=5, b=4, c=2.5
        expected_C = first_mass.channels()[Channel.STORAGE].C  # ≈ 180900 J/K

        result = group(two_mass_elements)
        asm = result.to_assembler()
        system, _ = asm.build(strict=False)
        assert system is not None

        C_room = math.exp(system.priors["C_room"][0])
        assert abs(C_room - expected_C) / expected_C < 0.01, (
            f"C_room ({C_room:.0f}) should match first IndoorMass capacity "
            f"({expected_C:.0f}), not their sum."
        )

    def test_two_indoor_mass_strict_raises(self, two_mass_elements):
        """In strict mode, multiple IndoorMass elements raise ValueError."""
        result = group(two_mass_elements)
        asm = result.to_assembler()
        with pytest.raises(ValueError, match="IndoorMass"):
            asm.build(strict=True)

    def test_single_indoor_mass_no_multiple_room_mass_problem(self):
        """The single-IndoorMass happy path must have no multiple_room_mass problem."""
        elements = [_indoor_mass(), _window("S")]
        result = group(elements)
        asm = result.to_assembler()
        system, problems = asm.build(strict=False)
        assert system is not None
        mm_probs = [p for p in problems if p.kind == "multiple_room_mass"]
        assert mm_probs == [], f"Single IndoorMass should produce no such problem; got: {mm_probs}"

    def test_single_indoor_mass_c_room_unchanged(self):
        """C_room from a single IndoorMass is unaffected by the new detection logic."""
        import math

        mass = _indoor_mass()  # a=5, b=4, c=2.5
        expected_C = mass.channels()[Channel.STORAGE].C

        result = group([mass, _window("S")])
        asm = result.to_assembler()
        system, _ = asm.build(strict=False)
        assert system is not None

        C_room = math.exp(system.priors["C_room"][0])
        assert abs(C_room - expected_C) / expected_C < 0.01
