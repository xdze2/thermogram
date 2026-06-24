# Modular RC model — implementation roadmap

Based on `modular_rc_proposal.md`. The channel-ownership model is **new and unvalidated** — it
is the thing most likely to be wrong and the cheapest to test. So the roadmap front-loads
**test cases over the data model** before building any engine, solver, or UI.

## Guiding principle

Two failure modes, tested in order:

1. **Expressiveness** — can a real building be *described* by the channels/modules at all?
   (the model is wrong). Cheap to test: needs no code, just a data table + hand-derived expected.
2. **Correctness** — it's describable, but the numbers come out wrong (the physics/code is
   wrong). Tested by golden values + dynamics sanity checks.

**Each stage's success criterion is the previous stage's output.** No stage trusts itself:
Stage 2 is judged by Stage 1's tests, Stage 3 by physical sanity, Stage 4 by Stage 3 being real.
This is what lets the work move fast without building on sand.

**Impatience note:** the UI is deliberately last. The payoff that scratches the
"I want to see something" itch is **Stage 3** (forward MC trajectories of the test buildings),
which can be a notebook/script before any Svelte — and those plots double as the best bug
detector the abstract model has.

---

## The test cases

A coverage matrix over the channels — each case stresses a different degree of freedom:

| case | stresses | question it answers |
|---|---|---|
| **cave / cellar** | ground coupling, no solar, near-constant | does STORAGE+ground work *without* solar? (and: Bacher's "constant room", the first fit target) |
| **caravan** | all-light, no STORAGE channel | does the model degrade to pure-resistive cleanly when no element offers STORAGE? |
| **regular house** | full mix: heavy walls + windows + vent | the south-window dual-channel case; heavy/light routing; the current default topology |
| **passive house** | extreme insulation, large solar gain, low H | do the *ratios* stay physical at the extremes? |
| **Earthship** | huge ground-coupled mass berm + big south glazing | both solar channels + ground-coupled STORAGE at once; the hardest expressiveness test |

**Scope discipline:** keep the cases to what the **current physics already covers**, so Stage 1
golden values are computable today from `priors.py`. The cave's ground coupling uses the
*current* floor boundary condition, not an idealized T_ground model (deferred). Otherwise the
golden tests have no ground truth and Stage 2 has nothing to preserve.

---

## Stage 0 — Hand-table the test cases as channel decompositions  *(no code)*

Write each building as an element list + its expected **channel decomposition**: for every
element, which channels it offers and which module owns each. If a case can't be filled in, the
channel model has a hole — found for the cost of a markdown table.

- [x] `docs/test_cases.md` — six buildings, each as elements → {channel: owner}; generic physics
      in `docs/physics_model.md`
- [x] Resolve `SOLAR_OPAQUE` as a 4th channel against the concrete Earthship/house walls
      (resolved for *exterior* opaque; **hole found** — transmitted solar onto interior mass is
      not covered, see Hole #1)
- [x] Confirm the south-window dual-channel and heavy/light routing read correctly on paper
- [x] Added the ITE/ITI renovated-wall case — the `RChain` layer-order stress test (Case 6)

**Verifiable:** every (element, channel) cell has exactly one owner; no case has an
unrepresentable element. Pure review artifact.

---

## Stage 1 — Golden-value prior tests on current `priors.py`  *(minimal code)*

Pin current behaviour before any refactor. Hand-compute (or read off current `priors.py`) the
expected ~5 parameter priors for each describable case; encode as pytest assertions. **This is
the regression net the modular refactor must keep green.**

- [x] `tests/fixtures/` — the test-case rooms as `Room` JSON: caravan, house, passive.
      Cave/earthship deferred (need ground/interior-solar physics, see test_cases.md scope).
      Every element carries an explicit `name`+`uid` — the uuid-default would otherwise make
      contribution labels (and thus snapshots) non-reproducible.
- [x] `tests/test_golden_priors.py` — hand-computed `mu`/`sigma` per param, derived
      *independently* from the ISO 6946 / rho·cp·d formulas (cross-checked against
      `build_priors` at rel_tol 1e-9), pinned at full precision.
- [x] Record full `RCModelOut` JSON snapshots per case (`tests/snapshots/`) for byte-diffing;
      `tests/regen_snapshots.py` regenerates them for *deliberate* behaviour changes only.

**Found by the pass (pinned as current behaviour, to revisit in Stage 2):**
- `alpha_eff` includes floors (incl. ground-contact) in the area-weighted average — only
  windows are excluded. A buried floor has no sol-air solar drive yet pulls weight here.
- `alpha_eff` contributions are an averaged breakdown, *not* additive — they don't sum to mu.
- Ground-contact floor U is the bare-stack ISO 6946 value (Rso=0, no T_ground model).

**Verifiable:** `uv run pytest tests/test_golden_priors.py` passes against current `priors.py`. ✓ (11 tests)

---

## Stage 2 — Channel/module refactor of `priors.py`  *(behaviour-preserving)*

Build the channel + module machinery and route the current topology through it. Success is
brutally simple: **the Stage 1 golden tests still pass and the JSON snapshots are unchanged.**

### 2a — Element channels

- [x] `thermal/api_models.py` — discriminated union (`WallElement`, `WindowElement`,
      `RoofElement`, `FloorElement`, `DoorElement`) on a shared `_ElementBase`;
      `is_ground_contact`→Floor, `shgc`→Window. Type-specific physics
      (`surface_resistances`/`solar_tilt_deg`/`irradiance_key`/`is_opaque`) is polymorphic
      on the subclasses — callers dispatch on the element, not `elem.type`. No `"type"`
      JSON alias / migration kept (only consumer of Room JSON is the test fixtures).
- [x] `EnvelopeElement.channels()` — landed as `channels.element_channels(elem) ->
      dict[Channel, Budget]`; conserved budgets computed once (CONDUCTION=U·A,
      SOLAR area, STORAGE=C_heavy). `Channel = (Mechanism, Source)` per physics_model §2.
- [x] Fixed the `elem.type == ...` branches in `iso6946.py`, `irradiance.py`,
      `state_space.py`, `priors.py` to use the polymorphic methods.

### 2b — Modules + assembler

- [x] `thermal/modules.py` — `FluxModule` base + `PriorTerm`; `RoomMass`, `Ventilation`,
      `WindowLoss`, `HeavyWall`, `SolarGain` (the current topology's modules). Each
      `derive_prior` reproduces the legacy per-parameter math; verified in isolation by
      `tests/test_modules_unit.py` against hand-values (13 tests).
- [x] `thermal/assembler.py` — `assemble(room)` routes (element, channel) cells to owning
      modules and **asserts exactly-once** (double-claim / unclaimed / stray are hard
      errors); `collect_priors` folds `PriorTerm`s (quadrature; area-weighted α) into
      `RCModelOut`. `tests/test_assembler.py` checks the invariant + legacy parity (8 tests).
- [ ] Heavy/light routing on actual `C_heavy` magnitude + per-element override (open hole
      #1) — **deferred**: changing it moves the C_wall snapshot, so it can't ride a
      behaviour-preserving stage. Currently routes on the heavy-layer ρ>500 mass (legacy).

### 2c — Wire into `build_priors`

- [x] `build_priors(room)` is now a thin `assemble(room)` → `collect_priors(...)`; legacy
      per-element loop + constants removed (live in `modules.py`/`channels.py`).

**Verifiable:** ✓ full suite green (52 tests); Stage 1 golden tests pass; `RCModelOut` JSON
byte-identical to Stage 1 snapshots. The channel model reproduced the current physics — the
abstraction earned its keep.

---

## Stage 3 — Forward MC simulation over the engine  *(the payoff + dynamics check)*

Sample priors → integrate → check trajectories against intuition. Validates **dynamics**,
which static priors don't.

Built the **general module-graph integrator** (not the 2R2C-reuse shortcut): modules grow a
`dynamics(params) -> Dynamics` method emitting nodes / inter-node couplings / source
couplings / source fluxes; the assembler folds them into a continuous `dx/dt = Ax + Bu` of
arbitrary state dimension. Node merging (same key → summed C/H) gives the per-element vs
aggregated granularity choice (physics_model §4).

- [x] `thermal/modules.py` — `Node`/`NodeCoupling`/`SourceCoupling`/`SourceFlux`/`Dynamics`
      vocabulary + `dynamics()` on `RoomMass`, `Ventilation`, `HeavyWall` (heavy → own mass
      node; light → direct T_sa→room), `SolarGain` (Q_room flux). Window conduction is folded
      into the H_ve coupling (no double-count).
- [x] `thermal/simulate.py` — `assemble_system(room, params, aggregate)` builds (A, B) by
      collecting module Dynamics, splitting sampled scalars across walls by U·A / mass share;
      `integrate()` (ZOH); `simulate(... n_draws ...)` → T_room ensemble. `sample_params`
      (Gaussian, clipped positive, seeded).
- [x] `tests/test_simulate_sanity.py` (7 tests): **correctness anchor** — assembled (A, B)
      equals `state_space.build_state_space` 2R2C exactly; node-merging (house 6 heavy nodes →
      1 aggregated; caravan → room-only); **physical ordering** — caravan tracks T_ext fastest,
      passive most damped (largest dominant τ), τ in 1 h–30 d range.
- [ ] Season-long drivers from Open-Meteo wiring; T_ground scenario signal — **deferred** (the
      describable cases need no T_ground; lands with the ground physics).
- [ ] Visualization (notebook/script ensemble plots) — **deferred** (chose tests-only;
      `simulate()` returns the ensemble ready to plot when wanted).

**Verifiable:** ✓ sanity assertions pass; assembled system proven identical to the known-good
2R2C engine (replaces the eyeball check). Full suite green (59 tests).

---

## Stage 4 — Topology rendering  *(small, high-value)*

Drawn from the **assembled** module graph (not a parameter sample): a two-layer
`thermal/draw.py` — a pure graph IR (`topology(room)` walks the modules' `dynamics()`)
and a `render(topo)` that lays the IR out with schemdraw. Labels are the *symbolic*
params (`H_env`/`H_int`/`C_wall`/…), so one schematic stands for the whole prior.

- [x] `thermal/draw.py` — `topology(room, aggregate)` → `Topology` IR (nodes /
      conductances / fluxes), deduping the parallel edges that collapse onto the
      aggregated `T_wall` node; `render(topo, fmt)` → SVG (native backend, no matplotlib)
      or PNG (needs matplotlib). schemdraw added as a project dep.
- [x] `GET /api/studies/{id}/topology?aggregate=&fmt=` serves the rendered SVG/PNG.
- [x] `tests/test_draw.py` (8): IR structure proves the schematic matches the module
      list — house → 2R2C edges, caravan degrades to a single room node, aggregation
      collapses 6 parallel walls to one edge; `render` smoke-draws SVG. `tests/test_api.py`
      (+3): endpoint serves SVG, 400 on no-room / bad-fmt.
- [x] Reference SVGs in `docs/diagrams/topology_{caravan,house,passive}.svg`.

**Verifiable:** ✓ each describable case renders a legible RC schematic matching its module
list; full suite green (70 tests).

---

## Stage 5 — Expose to API / frontend  *(now it's worth it)*

There is something real and trusted underneath to show. **Backend landed; frontend deferred
to its own pass.**

- [x] `GET /api/modules` — `{name, form, summary, params, signals, extra_states, owns}` for
      every known module, from a declarative `MODULE_CATALOGUE` in `modules.py`
      (`DirectLoss` is split into `Ventilation` + `WindowLoss` in the implementation).
- [x] `RCModelOut.modules` — `active_modules()` reports the room's modules **deduped by
      class** (6 heavy walls → one `HeavyWall`, mirroring the aggregated 2R2C topology),
      with `signals_required`, `n_free_params`, `n_states` (aggregated: distinct mass-node
      keys, so caravan=1 / house=2), and an `identifiability_warning` flagged explicitly as
      a *fit* concern, not a *simulation* one. A light `HeavyWall` instance narrows away its
      `T_wall` extra-state.
- [x] `tests/test_api.py` (+2) — `/api/modules` includes `HeavyWall`/`Ventilation`/
      `SolarGain`; `RCModelOut.modules` reports the active set + signals + state count.
      `tests/test_assembler.py` (+4) — catalogue covers every assembled class, dedup +
      state-count, caravan single-state, warning trips over a monkeypatched limit. Golden
      snapshots regenerated (**purely additive** — the five priors are byte-unchanged).
- [x] Frontend — **module readout + real schematic** (the *consequence* side):
      - `ActiveModuleOut.count` added (additive; snapshots regenerated) so the panel shows
        `HeavyWall ×6` rather than hiding multiplicity behind the class-dedup.
      - `frontend/src/lib/ModulePanel.svelte` — read-only "Model" panel from `RCModelOut`:
        per-module count / canonical form / free params / routed element / `← signal`
        badges, a `needs:` footer, and the `identifiability_warning` (shown only when set).
      - **Killed the fake Mermaid diagram.** `StudyEditor.svelte` now embeds
        `GET …/topology` (the real Stage-4 `draw.py` schematic), cache-busted on each
        recompute. Verified in the running app: house → `2 states` + `T_wall` node;
        caravan → `1 state`, no wall node (the old hardcoded graph drew a phantom `C_wall`).
- [ ] Frontend — **forward-simulation view** (ensemble plot + scenario sliders) — **deferred**:
      needs a `/simulate` endpoint + the deferred Stage 3 driver wiring (Open-Meteo +
      T_ground). See "What's next" below.

**Verifiable:** ✓ API tests pass; `GET /api/modules` + `RCModelOut.modules` expose the
assembled topology; the UI shows the *real* schematic + module readout; full suite green
(76 tests). Simulation view pending.

---

## What's next  *(ordered: cheapest-honest → biggest payoff)*

The engine + read-only exposure are done. The remaining work splits into (A) closing small
honesty gaps, (B) the real *choice* the proposal promises, and (C) the simulation toy.

### A. Light-instance param narrowing  *(small, no physics change)*

The `ModulePanel` lists `C_wall` under `HeavyWall` even for the **caravan** (all-light),
because per-module `params` come from the static `MODULE_CATALOGUE`, not from what a *light*
instance actually contributes. The `n_states`/schematic are already correct; only the
per-module param list over-reports. Fix mirrors the existing `_instance_extra_states`:
add `_instance_params(mod)` that drops `C_wall` (and the `STORAGE@—` channel from `owns`)
for a light `HeavyWall`. Update `active_modules` + one assembler test + regen snapshots
(additive). ~30 min.

### B. Heavy/light routing override — the actual module *choice*  *(the proposal's core UX)*

This is **open hole #1** (deferred from Stage 2b) and the real "module choice in the UI":

- **Model**: add `thermal_mass: "auto" | "heavy" | "light"` to the opaque element model
  (default `"auto"`). `assemble()` routes a wall's `CONDUCTION` to `HeavyWall`-with-node vs
  direct on this override instead of purely on `is_heavy`. **This moves the `C_wall`/state
  snapshots** — it is a deliberate behaviour change (regen snapshots, review the diff), not
  a behaviour-preserving step. That is why it never rode Stage 2.
- **Assembler**: `is_heavy` becomes "offers STORAGE *and* not overridden to light"; a wall
  forced `heavy` with no ρ>500 layers needs a fallback C (or a warning).
- **API**: the override round-trips through `Room` JSON (already persisted per study).
- **Frontend**: a 3-way toggle **on the `ElementCard`** (`auto · heavy · light`) — the choice
  lives where the element is edited (cause); the `ModulePanel` + schematic already built
  show the effect, live. Editing the toggle visibly moves both.
- **Tests**: routing flips the state count (force a brick wall light → caravan-like 1-state;
  force a light wall heavy → gains a node); snapshot diff is the C_wall delta only.

### C. Forward-simulation view — the Bret-Victor toy  *(biggest, needs driver wiring first)*

The `simulate()` engine (Stage 3) is ready and returns a plottable T_room ensemble; what's
missing is the *drivers* and an endpoint:

1. **Driver wiring** (the deferred Stage 3 item): build `T_sa`/`Q_room` from a scenario —
   synthetic first (sinusoid T_ext + diurnal solar, zero deps, runs standalone), then real
   Open-Meteo. Add a prescribed `T_ground` scenario signal for when `HeavySlab` lands.
2. **`POST /api/studies/{id}/simulate`** — `{n_draws, dt, scenario}` → the room-node
   ensemble (mean + p10/p90 bands). Reuses `sample_params` + `assemble_system` + `integrate`.
3. **Frontend**: ensemble plot (reuse the Plotly setup in `DataPreview.svelte`) + scenario
   sliders (ACH, set-point, solar scale). **No identifiability limit here** — forward
   integration needs no inversion; the warning stays a *fit*-only concern.

**Suggested order:** A (quick honesty fix) → B (the headline choice UX) → C (the toy). A and
B share the `ModulePanel`/schematic already built; C is the largest and most independent.

---

## Deferred (after the engine is solid)

These belong to **③ the fit** (`reading_note_bacher_madsen_2011.md`), and start *only* on the
constant-room cases (cave/cellar):

- [ ] `HeavySlab` + a T_ground source (Kusuda–Achenbach or measured)
- [ ] NumPy Kalman prediction-error likelihood over the assembled LTI system (phase 2a, ML-only)
- [ ] White-residual diagnostics (ACF + cumulated periodogram) as the topology-adequacy gate
- [ ] ML → MAP: add the ISO 6946 prior term; report prior-vs-data contribution per parameter
