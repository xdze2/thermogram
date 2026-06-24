# Modular RC model — implementation TODO

Based on `modular_rc_proposal.md`.

## Step 1 — Discriminated union for element types

Replace the flat `EnvelopeElement` (with `type: ElementType` + optional fields) with a
proper discriminated union: `WallElement`, `WindowElement`, `RoofElement`, `FloorElement`,
`DoorElement`, each with only the fields that make sense for that type.

- `kind` field as discriminator (Literal["wall"] etc.)
- `is_ground_contact` moves from `EnvelopeElement` to `FloorElement` only
- `shgc` moves to `WindowElement` only
- Keep `"type"` as a validator alias during transition so existing JSON still works
- [ ] `thermal/api_models.py` — define the five subtypes + `EnvelopeElement` union
- [ ] Update `model_validator` (layers-or-override check) to live on each subtype
- [ ] Fix all `elem.type == ElementType.window` branches in `iso6946.py`, `irradiance.py`, `state_space.py`, `priors.py`

**Verifiable:** `uv run pytest` passes unchanged.

---

## Step 2 — Scoped per-element-type helpers in `priors.py`

Extract existing prior logic into typed helper functions, one per element type / physics path.

- [ ] `_h_env_contrib(elem: WallElement | RoofElement | FloorElement) -> ContributionOut`
- [ ] `_h_win_contrib(elem: WindowElement) -> ContributionOut`
- [ ] `_c_wall_contrib(elem: WallElement | RoofElement) -> ContributionOut | None`
- [ ] `build_priors` becomes a dispatch loop over typed helpers

**Verifiable:** Same test suite, same numerical outputs — pure refactor.

---

## Step 3 — `FluxModule` dataclass in `thermal/modules.py`

Define the base abstraction and implement the two implicit modules already in the codebase.

```python
@dataclass
class FluxModule:
    name: str
    params: list[str]
    signals: list[str]
    extra_states: list[str]

    def prior(self, elements) -> dict[str, tuple[float, float]]: ...
    def flux_room(self, params, signals, states) -> float: ...
    def state_ode(self, params, signals, states) -> dict[str, float]: ...
```

- [ ] `thermal/modules.py` — `FluxModule` base + `HeavyWallModule` + `VentilationModule`
- [ ] `HeavyWallModule.prior()` wraps the Step 2 helpers for H_env, C_wall, alpha
- [ ] `VentilationModule.prior()` wraps the H_ve helper
- [ ] `tests/test_modules.py` — instantiate modules, call `.prior()` on BRICK_ROOM fixture, assert same mu/sigma as current API

**Verifiable:** New `test_modules.py` passes; existing tests unchanged.

---

## Step 4 — Wire modules into `build_priors`

Replace `build_priors` internals with module assembly loop.

- [ ] `build_priors(room)` assembles `[RoomMassModule(), HeavyWallModule(), VentilationModule(), FastLossModule()]`
- [ ] Collects `m.prior(room.elements)` for each module, assembles `RCModelOut` from results
- [ ] Record a JSON fixture of the current BRICK_ROOM response and diff against new output

**Verifiable:** Full test suite green; JSON response byte-identical to recorded fixture.

---

## Step 5 — `HeavySlabModule` + ground-contact floor

- [ ] `HeavySlabModule.prior()` reads `FloorElement` where `is_ground_contact=True`
- [ ] Priors: `H_slab_out`, `H_slab_in`, `C_slab`
- [ ] `tests/test_modules.py` — add slab floor element, assert those keys appear in priors

**Verifiable:** `test_ground_slab_prior` passes.

---

## Step 6 — Expose modules to the API / frontend

- [ ] `GET /api/modules` — returns list of `{name, params, signals, extra_states}` for all known modules
- [ ] Add `modules` field to `RCModelOut` listing active modules and their signal requirements
- [ ] Frontend: show signal-availability warning when a required signal is not configured
- [ ] `tests/test_api.py` — `test_schema_returns_modules` asserts GET /api/modules includes at least `HeavyWall` and `Ventilation`

**Verifiable:** New API test passes; frontend shows warning for missing signals.
