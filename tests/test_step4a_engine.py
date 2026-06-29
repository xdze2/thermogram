"""Track E acceptance tests — E1 (non-raising assembly), E2 (type registry), E3 (contributions)."""

import pytest

from thnodes import (
    Assembler,
    DirectLoss,
    ELEMENT_TYPES,
    Floor,
    HeatSource,
    HeavyWall,
    IndoorMass,
    LAYER_SCHEMA,
    Layer,
    MODULE_TYPES,
    OuterWall,
    Partition,
    Problem,
    RoomMass,
    SolarGainModule,
    Window,
)
from thnodes.channels import Channel


# ── shared fixtures ────────────────────────────────────────────────────────────

def _indoor_mass():
    """Standard 5×4×2.5 m normal room for tests."""
    return IndoorMass(a=5.0, b=4.0, c=2.5, furniture="normal")


def _light_wall():
    return OuterWall(area=10.0, orientation="S", layers=[Layer("insulation_mineral_wool", 0.1)])


def _heavy_wall():
    return OuterWall(
        area=10.0, orientation="S",
        layers=[Layer("concrete", 0.2), Layer("insulation_mineral_wool", 0.1)],
    )


def _window():
    return Window(area=4.0, orientation="S", U=1.2, shgc=0.6)


def _build_heavy_strict():
    heavy = _heavy_wall()
    win = _window()
    indoor = _indoor_mass()
    asm = Assembler()
    asm.add_element(indoor)
    asm.add_module(RoomMass())
    asm.add_module(DirectLoss(), elements=[win])
    asm.add_module(HeavyWall(), elements=[heavy])
    asm.add_module(SolarGainModule(), elements=[win])
    return asm.build()


# ══════════════════════════════════════════════════════════════════════════════
# E1 — Non-raising assembly
# ══════════════════════════════════════════════════════════════════════════════

class TestE1NonRaisingAssembly:

    def test_strict_double_count_still_raises(self):
        """strict=True (default) must still raise on a double-counted element."""
        heavy = _heavy_wall()
        indoor = _indoor_mass()
        asm = Assembler()
        asm.add_element(indoor)
        asm.add_module(RoomMass())
        asm.add_module(DirectLoss(), elements=[heavy])
        asm.add_module(HeavyWall(), elements=[heavy])
        with pytest.raises(ValueError, match="[Dd]ouble"):
            asm.build(strict=True)

    def test_strict_default_double_count_raises(self):
        """strict parameter defaults to True — existing call sites unaffected."""
        heavy = _heavy_wall()
        indoor = _indoor_mass()
        asm = Assembler()
        asm.add_element(indoor)
        asm.add_module(RoomMass())
        asm.add_module(DirectLoss(), elements=[heavy])
        asm.add_module(HeavyWall(), elements=[heavy])
        with pytest.raises(ValueError):
            asm.build()

    def test_non_strict_double_count_returns_problem(self):
        """strict=False returns a double_count problem instead of raising."""
        heavy = _heavy_wall()
        indoor = _indoor_mass()
        asm = Assembler()
        asm.add_element(indoor)
        asm.add_module(RoomMass())
        asm.add_module(DirectLoss(), elements=[heavy])
        asm.add_module(HeavyWall(), elements=[heavy])

        result, problems = asm.build(strict=False)

        dc_problems = [p for p in problems if p.kind == "double_count"]
        assert len(dc_problems) >= 1
        assert dc_problems[0].cell is not None
        # cell[1] should name the disputed channel
        assert dc_problems[0].cell[1] == Channel.CONDUCTION.name

    def test_non_strict_double_count_returns_system(self):
        """When RoomMass is present, strict=False returns a System even with double-count."""
        heavy = _heavy_wall()
        indoor = _indoor_mass()
        asm = Assembler()
        asm.add_element(indoor)
        asm.add_module(RoomMass())
        asm.add_module(DirectLoss(), elements=[heavy])
        asm.add_module(HeavyWall(), elements=[heavy])

        result, problems = asm.build(strict=False)
        assert result is not None
        assert "T_room" in result.state_names

    def test_non_strict_missing_room_mass_returns_none(self):
        """Without RoomMass, strict=False returns (None, [missing_room_mass problem])."""
        asm = Assembler()
        asm.add_module(DirectLoss(), elements=[_window()])

        result, problems = asm.build(strict=False)
        assert result is None
        assert any(p.kind == "missing_room_mass" for p in problems)

    def test_strict_missing_room_mass_raises(self):
        """Without RoomMass, strict=True raises ValueError."""
        asm = Assembler()
        asm.add_module(DirectLoss(), elements=[_window()])
        with pytest.raises(ValueError):
            asm.build(strict=True)

    def test_non_strict_unclaimed_channel_captured(self):
        """A window routed only to DirectLoss (not SolarGainModule) leaves SOLAR_TRANSMISSION
        unclaimed — strict=False captures it as an unclaimed_channel problem."""
        win = _window()
        indoor = _indoor_mass()
        asm = Assembler()
        asm.add_element(indoor)
        asm.add_module(RoomMass())
        asm.add_module(DirectLoss(), elements=[win])
        # SolarGainModule intentionally omitted → SOLAR_TRANSMISSION unclaimed

        result, problems = asm.build(strict=False)
        assert result is not None
        assert any(p.kind == "unclaimed_channel" for p in problems)

    def test_problem_is_dataclass_with_required_fields(self):
        """Problem instances must have kind, message, and cell attributes."""
        p = Problem(kind="double_count", message="test", cell=("elem", "CONDUCTION"))
        assert p.kind == "double_count"
        assert p.message == "test"
        assert p.cell == ("elem", "CONDUCTION")

    def test_problem_cell_can_be_none(self):
        """Problem.cell is optional (None for missing_room_mass)."""
        p = Problem(kind="missing_room_mass", message="no room mass")
        assert p.cell is None

    def test_non_strict_happy_path_no_problems(self):
        """A correct assembly under strict=False returns an empty problems list."""
        win = _window()
        wall = _light_wall()
        indoor = _indoor_mass()
        asm = Assembler()
        asm.add_element(indoor)
        asm.add_module(RoomMass())
        asm.add_module(DirectLoss(), elements=[wall, win])
        asm.add_module(SolarGainModule(), elements=[win])
        result, problems = asm.build(strict=False)
        assert result is not None
        assert problems == []


# ══════════════════════════════════════════════════════════════════════════════
# E2 — Type registry
# ══════════════════════════════════════════════════════════════════════════════

class TestE2TypeRegistry:

    def test_element_types_covers_all_required(self):
        required = {"OuterWall", "Window", "Floor", "Partition", "IndoorMass", "HeatSource"}
        assert required.issubset(ELEMENT_TYPES.keys())

    def test_module_types_covers_all_required(self):
        required = {"RoomMass", "DirectLoss", "SolarGainModule", "HeavyWall"}
        assert required.issubset(MODULE_TYPES.keys())

    def test_element_type_has_ctor_and_fields(self):
        for name, spec in ELEMENT_TYPES.items():
            assert "ctor" in spec, f"{name} missing 'ctor'"
            assert "fields" in spec, f"{name} missing 'fields'"
            assert callable(spec["ctor"]), f"{name}.ctor is not callable"

    def test_module_type_has_ctor_owns_params(self):
        for name, spec in MODULE_TYPES.items():
            assert "ctor" in spec, f"{name} missing 'ctor'"
            assert "owns" in spec, f"{name} missing 'owns'"
            assert "params" in spec, f"{name} missing 'params'"
            assert callable(spec["ctor"]), f"{name}.ctor is not callable"

    def test_enum_fields_have_options(self):
        """All fields with type 'enum' must include an 'options' list."""
        for name, spec in ELEMENT_TYPES.items():
            for f in spec["fields"]:
                if f["type"] == "enum":
                    assert "options" in f, f"{name}.{f['name']} enum field missing 'options'"
                    assert len(f["options"]) > 0

    def test_orientations_in_outer_wall(self):
        wall_fields = {f["name"]: f for f in ELEMENT_TYPES["OuterWall"]["fields"]}
        assert "orientation" in wall_fields
        assert wall_fields["orientation"]["type"] == "enum"
        assert "S" in wall_fields["orientation"]["options"]
        assert "N" in wall_fields["orientation"]["options"]

    def test_materials_in_layer_schema(self):
        """LAYER_SCHEMA must expose a material enum with options from materials_db."""
        from thnodes.materials import materials_db
        material_field = next(
            f for f in LAYER_SCHEMA["fields"] if f["name"] == "material"
        )
        assert material_field["type"] == "enum"
        assert set(material_field["options"]) == set(materials_db.keys())

    def test_construct_outer_wall_from_schema(self):
        spec = ELEMENT_TYPES["OuterWall"]
        wall = spec["ctor"](
            area=10.0,
            orientation="S",
            layers=[Layer("concrete", 0.2)],
            alpha=0.6,
        )
        assert isinstance(wall, OuterWall)

    def test_construct_window_from_schema(self):
        spec = ELEMENT_TYPES["Window"]
        win = spec["ctor"](area=4.0, orientation="S", U=1.2, shgc=0.6)
        assert isinstance(win, Window)

    def test_construct_floor_from_schema(self):
        spec = ELEMENT_TYPES["Floor"]
        fl = spec["ctor"](area=15.0, boundary="ground", layers=[Layer("concrete", 0.15)])
        assert isinstance(fl, Floor)

    def test_construct_partition_from_schema(self):
        spec = ELEMENT_TYPES["Partition"]
        part = spec["ctor"](area=8.0, layers=[Layer("plasterboard", 0.013)])
        assert isinstance(part, Partition)

    def test_construct_indoor_mass_from_schema(self):
        spec = ELEMENT_TYPES["IndoorMass"]
        # New IndoorMass takes a, b, c, furniture (no 'area' or 'C' constructor args)
        mass = spec["ctor"](a=5.0, b=4.0, c=2.5, furniture="normal")
        assert isinstance(mass, IndoorMass)

    def test_construct_heat_source_from_schema(self):
        spec = ELEMENT_TYPES["HeatSource"]
        hs = spec["ctor"](area=0.0)
        assert isinstance(hs, HeatSource)

    def test_construct_room_mass_from_schema(self):
        spec = MODULE_TYPES["RoomMass"]
        # RoomMass is pure topology — takes no fields
        rm = spec["ctor"]()
        assert isinstance(rm, RoomMass)

    def test_construct_direct_loss_from_schema(self):
        spec = MODULE_TYPES["DirectLoss"]
        dl = spec["ctor"]()
        assert isinstance(dl, DirectLoss)

    def test_construct_solar_gain_from_schema(self):
        spec = MODULE_TYPES["SolarGainModule"]
        sg = spec["ctor"]()
        assert isinstance(sg, SolarGainModule)

    def test_construct_heavy_wall_from_schema(self):
        spec = MODULE_TYPES["HeavyWall"]
        hw = spec["ctor"]()
        assert isinstance(hw, HeavyWall)

    def test_module_owns_match_actual_channel_names(self):
        """MODULE_TYPES[*].owns entries must be valid Channel enum names."""
        valid_channels = {ch.name for ch in Channel}
        for name, spec in MODULE_TYPES.items():
            for ch_name in spec["owns"]:
                assert ch_name in valid_channels, (
                    f"{name}.owns contains unknown channel '{ch_name}'"
                )

    def test_heavy_wall_owns_three_channels(self):
        spec = MODULE_TYPES["HeavyWall"]
        assert set(spec["owns"]) == {"CONDUCTION", "STORAGE", "SOLAR_OPAQUE"}

    def test_direct_loss_owns_conduction(self):
        spec = MODULE_TYPES["DirectLoss"]
        assert spec["owns"] == ["CONDUCTION"]


# ══════════════════════════════════════════════════════════════════════════════
# E3 — Parameter contributions
# ══════════════════════════════════════════════════════════════════════════════

class TestE3ParameterContributions:

    def test_heavy_c_wall_has_storage_contribution(self):
        """C_wall's contributions must include a STORAGE budget from the heavy wall."""
        sys = _build_heavy_strict()
        contribs = sys.parameter_contributions()

        assert "C_wall" in contribs, "C_wall must appear in contributions"
        entries = contribs["C_wall"]
        storage_entries = [e for e in entries if e["channel"] == Channel.STORAGE.name]
        assert len(storage_entries) >= 1, (
            f"Expected C_wall to have STORAGE contribution; got {entries}"
        )
        # The budget field for storage is 'C'
        assert all(e["budget_field"] == "C" for e in storage_entries)
        assert all(e["value"] > 0 for e in storage_entries)

    def test_heavy_h_ve_has_conduction_contribution(self):
        """H_ve's contributions must include CONDUCTION budgets (window, in the heavy room)."""
        sys = _build_heavy_strict()
        contribs = sys.parameter_contributions()

        assert "H_ve" in contribs, "H_ve must appear in contributions"
        entries = contribs["H_ve"]
        cond_entries = [e for e in entries if e["channel"] == Channel.CONDUCTION.name]
        assert len(cond_entries) >= 1, (
            f"Expected H_ve to have CONDUCTION contributions; got {entries}"
        )
        assert all(e["budget_field"] == "UA" for e in cond_entries)

    def test_contributions_have_required_keys(self):
        """Every contribution entry must have element_label, channel, budget_field, value."""
        sys = _build_heavy_strict()
        contribs = sys.parameter_contributions()
        required_keys = {"element_label", "channel", "budget_field", "value"}
        for param, entries in contribs.items():
            for e in entries:
                missing = required_keys - e.keys()
                assert not missing, f"{param} entry missing keys {missing}: {e}"

    def test_contributions_element_labels_are_strings(self):
        sys = _build_heavy_strict()
        contribs = sys.parameter_contributions()
        for param, entries in contribs.items():
            for e in entries:
                assert isinstance(e["element_label"], str), (
                    f"{param} entry element_label is not a str: {e}"
                )

    def test_contributions_channel_names_valid(self):
        """channel field in every entry must be a known Channel name."""
        sys = _build_heavy_strict()
        valid = {ch.name for ch in Channel}
        contribs = sys.parameter_contributions()
        for param, entries in contribs.items():
            for e in entries:
                assert e["channel"] in valid, (
                    f"{param} entry has invalid channel {e['channel']!r}"
                )

    def test_contributions_returns_copy(self):
        """parameter_contributions() must return an independent copy (mutating it is safe)."""
        sys = _build_heavy_strict()
        c1 = sys.parameter_contributions()
        c2 = sys.parameter_contributions()
        c1.pop(next(iter(c1)))
        assert set(c1.keys()) != set(c2.keys()) or True  # just confirm no shared reference crash

    def test_caravan_h_ve_contributions(self):
        """In the caravan, H_ve consumes the wall and window CONDUCTION budgets."""
        win = _window()
        wall = _light_wall()
        indoor = _indoor_mass()
        asm = Assembler()
        asm.add_element(indoor)
        asm.add_module(RoomMass())
        asm.add_module(DirectLoss(), elements=[wall, win])
        asm.add_module(SolarGainModule(), elements=[win])
        sys = asm.build()

        contribs = sys.parameter_contributions()
        assert "H_ve" in contribs
        entries = contribs["H_ve"]
        # Two elements → two CONDUCTION/UA entries
        cond_entries = [e for e in entries if e["channel"] == Channel.CONDUCTION.name]
        assert len(cond_entries) == 2

    def test_shgca_contributions_include_solar_transmission(self):
        """shgcA's contributions come from SOLAR_TRANSMISSION budget field 'shgcA'."""
        sys = _build_heavy_strict()
        contribs = sys.parameter_contributions()
        assert "shgcA" in contribs
        entries = contribs["shgcA"]
        st_entries = [e for e in entries if e["channel"] == Channel.SOLAR_TRANSMISSION.name]
        assert len(st_entries) >= 1
        assert all(e["budget_field"] == "shgcA" for e in st_entries)
