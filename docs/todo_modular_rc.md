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

- [ ] `tests/fixtures/` — the test-case rooms as `Room` JSON (cave, caravan, house, passive,
      earthship where current physics allows)
- [ ] `tests/test_golden_priors.py` — `build_priors(case).<param>.mu ≈ X ± tol` for each case
- [ ] Record full `RCModelOut` JSON snapshots per case for byte-diffing in later stages

**Verifiable:** `uv run pytest tests/test_golden_priors.py` passes against current `priors.py`.

---

## Stage 2 — Channel/module refactor of `priors.py`  *(behaviour-preserving)*

Build the channel + module machinery and route the current topology through it. Success is
brutally simple: **the Stage 1 golden tests still pass and the JSON snapshots are unchanged.**

### 2a — Element channels

- [ ] `thermal/api_models.py` — discriminated union (`WallElement`, `WindowElement`,
      `RoofElement`, `FloorElement`, `DoorElement`); `is_ground_contact`→Floor, `shgc`→Window;
      keep `"type"` alias for existing JSON
- [ ] `EnvelopeElement.channels() -> dict[Channel, Budget]` — conserved budgets computed once
      (CONDUCTION=U·A, SOLAR_TRANSMISSION=SHGC·A, SOLAR_OPAQUE=α·A, STORAGE=C_heavy)
- [ ] Fix `elem.type == ...` branches in `iso6946.py`, `irradiance.py`, `state_space.py`,
      `priors.py`

### 2b — Modules + assembler

- [ ] `thermal/modules.py` — `FluxModule` base + `Channel`/`Budget` + four flux forms
- [ ] `RoomMass`, `DirectLoss`, `SolarGain`, `HeavyWall` (the current default topology's modules)
- [ ] `thermal/assembler.py` — route (element, channel) cells to owning modules; **assert
      exactly-once per cell**; collect params/signals/states
- [ ] Heavy/light routing: inferred from `is_heavy`, with per-element override field

### 2c — Wire into `build_priors`

- [ ] `build_priors(room)` becomes: compute channels → assemble modules → collect
      `derive_priors` → `RCModelOut`

**Verifiable:** full suite green; Stage 1 golden tests pass; `RCModelOut` JSON byte-identical to
Stage 1 snapshots. The channel model has reproduced the current physics — the abstraction has
earned its keep.

---

## Stage 3 — Forward MC simulation over the engine  *(the payoff + dynamics check)*

Sample priors → integrate (reuse `forward_sim`) → eyeball trajectories against intuition. This
validates **dynamics**, which static priors don't, and is the first genuinely motivating thing
to look at.

- [ ] `thermal/simulate.py` — `simulate(modules, priors, drivers, n_draws)` → ensemble of
      T_room (and node) trajectories; scenario inputs for variable states (heating/occupancy/
      window via `SourceFlux`)
- [ ] Season-long drivers from existing Open-Meteo wiring; T_ground as prescribed scenario signal
- [ ] `notebooks/` or script — plot the five buildings' ensembles with uncertainty envelope
- [ ] `tests/test_simulate_sanity.py` — physical-ordering assertions (à la `inertie_nocturne`
      console checks): caravan tracks T_ext fastest; passive most damped; cave near-flat at
      ground temp; τ in plausible range; passive τ > caravan τ

**Verifiable:** sanity assertions pass; the plots match physical intuition per case.

---

## Stage 4 — Topology rendering  *(small, high-value)*

- [ ] `thermal/draw.py` — assembled module graph → schemdraw → SVG/PNG (server-side)
- [ ] Endpoint to serve the rendered topology for a study

**Verifiable:** each test case renders a legible RC schematic matching its module list.

---

## Stage 5 — Expose to API / frontend  *(now it's worth it)*

There is something real and trusted underneath to show.

- [ ] `GET /api/modules` — `{name, params, signals, extra_states, owns}` for all known modules
- [ ] `RCModelOut.modules` — active modules + signal requirements + identifiability warning
      (flagged as a *fit* concern, not a *simulation* one)
- [ ] Frontend: forward-simulation view (ensemble plot + scenario sliders); module list with
      signal-availability warnings; topology schematic
- [ ] `tests/test_api.py` — `GET /api/modules` includes at least `HeavyWall`, `DirectLoss`,
      `SolarGain`

**Verifiable:** API tests pass; frontend shows simulation, modules, warnings, and schematic.

---

## Deferred (after the engine is solid)

These belong to **③ the fit** (`reading_note_bacher_madsen_2011.md`), and start *only* on the
constant-room cases (cave/cellar):

- [ ] `HeavySlab` + a T_ground source (Kusuda–Achenbach or measured)
- [ ] NumPy Kalman prediction-error likelihood over the assembled LTI system (phase 2a, ML-only)
- [ ] White-residual diagnostics (ACF + cumulated periodogram) as the topology-adequacy gate
- [ ] ML → MAP: add the ISO 6946 prior term; report prior-vs-data contribution per parameter
