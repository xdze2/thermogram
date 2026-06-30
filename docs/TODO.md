# thnodes — Implementation TODO

**Audience: a fresh model session (or a sub-agent) with no prior context.** Read these first:

0. `docs/specs/00_overview.md` — the authoritative spec set + reading order. **Start here.**
1. `docs/specs/15_signals_and_grouping.md` — **the current direction.** The authoring model:
   first-class Signals, per-element boundaries, deterministic grouping into *derived* modules.
   This supersedes the old element×channel routing-matrix authoring.
2. `docs/specs/40_physics.md` — engine invariants (star topology, channels, four forms, the
   band rule, **I8 grouping rule**).
3. `docs/roadmap.md` — sequencing and *why*. The active phase is **Phase D**.
4. `docs/background/app_proposal.md` — full design rationale (the *why* behind the physics).

---

## Where we are (2026-06b)

- **Steps 0–1 are DONE** — assembler, four flux forms, forward sim, identifiability lens; pure
  NumPy; tests green. See [§Done ledger](#done-ledger).
- **Step 4a (authoring app) is BUILT but on the OLD model** — FastAPI + Svelte, multi-model
  local persistence, server-rendered topology SVG, `/assembly` projection. It authors via the
  generic **routing matrix**, which we are replacing.
- **CURRENT FOCUS — Phase D: get the data model + element→RC mapping right**, by prototyping the
  signal-grouping model end to end. **Computation (the fit, Steps 2–3) is deferred** until the
  data model is settled. A wrong data model poisons every layer above it.

> **The one decision driving this file:** nail the *concepts* (Signals, boundaries, treatments,
> the grouping rule, derived modules) before more numerics. Forward-sim is "good enough" for
> prototyping; the fit waits.

**Golden rules (unchanged)**
- `uv`-managed. Physics runs **server-side**. Engine (Steps 0–1 + the grouping rule) stays
  **pure NumPy** — no JAX outside the fit core.
- Modules are **star branches**: one terminal is `T_room`, the other is a **boundary signal**;
  private states stay private to the owning module.
- Channels are **internal conservation bookkeeping**, *not* the authoring vocabulary (spec 15).
- Local, single-user, no auth/DB/multi-tenancy. Persistence is local `user_data/{uid}.json`.
- The fit target (later) is the **full posterior** via JAX-Kalman + NumPyro NUTS, hand-rolled
  filter. CTSM-R is a validation oracle only — never a runtime dep.
- Validate **headless first** with the canonical rooms; the rooms *are* the test suite.

---

# Phase D — Data-model & element→RC mapping (ACTIVE)

**Goal:** implement and prototype `specs/15_signals_and_grouping.md` end to end, then *use* it
until the concepts feel right. The deliverable of this phase is **conviction that the data
model is correct**, evidenced by: the canonical rooms authored through the new model produce
exactly the module sets a building physicist would draw, with no routing UI and no double-counts.

## How this phase is organized (separable, sub-agent-friendly)

Each workstream below is a **self-contained brief** a sub-agent can take with only the specs +
this section as context. The **only hard ordering constraint is D1 → (D2, D3, D4)**: the
document/data shapes must exist before grouping, API, or UI build on them. D2/D3/D4 parallelize
once D1 lands.

```
        ┌──────────────────────────────┐
        │ D1  Document & registry shapes │   (land first; pure data, no physics)
        └──────────────┬───────────────┘
            ┌──────────┼───────────────┬─────────────┐
            ▼          ▼               ▼             ▼
        ┌───────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐
        │ D2    │  │ D3         │  │ D4         │  │ D5         │
        │ rule  │  │ API/assembly│  │ element UI │  │ prototype  │
        └───────┘  └────────────┘  └────────────┘  └────────────┘
        (D5 = the validation/usability harness; consumes D2 directly, headless — can start
         the moment D2 has a first version, in parallel with D3/D4)
```

**Suggested dispatch:** D1 solo first. Then D2 + D3 in parallel (backend pair), D4 (frontend)
against fixtures, D5 (headless harness) against D2. Integrate last.

---

## D1 — Document & registry shapes  *(land first; no physics)*

**Context to read:** spec 15 (Signal object, signal roles, element boundary fields, treatment
menus), spec 30 → "Direction change: signal-grouping deltas".

**Scope (pure data-model; the assembler/UI come later):**

- **Add the `Signal` document resource:** `{id, name, kind, role, meta}` with
  `role ∈ {exterior, ground, adjacent, solar, prescribed}`, `kind ∈ {temperature, irradiance,
  flux}`. Keep it **binding-agnostic** — no data/source field yet (future data-source layer).
- **Add per-element boundary fields:** generalize `Floor.boundary`. `OuterWall`/`Window` keep
  `orientation` but it now *pins* `T_ext` + `G_sol_<orient>`; `Partition` gains an `adjacent`
  room-label field; `Floor.boundary`'s `adjacent` option gains a room label.
- **Add the element `treatment` field** (e.g. `thermal_mass` | `simple_loss`); `[]`/forced for
  every element except heavy walls.
- **Extend the registry** (`registry.py`): per element type, a **boundary descriptor**
  (`{field, role}`) and a **treatment menu** (`[{key, label, default}]` or empty=forced).
- **Remove routing from the document model:** drop `doc.routes` and `Module.element_ids`
  (modules become derived in D2/D3 — leave a stub so the app still loads until D3 lands, or
  coordinate the cutover).

**Acceptance:** the document round-trips with Signals + element boundaries + treatments; the
registry exposes boundary descriptors and treatment menus; no physics changed. Unit tests on
the shapes only.

---

## D2 — The grouping rule  *(the heart of the phase)*

**Context:** spec 40 I8, spec 15 §"Grouping rule" + §"Treatment menus". This is where the
concept lives or dies — give it the most tests and prototyping.

**Scope (assembler, pure NumPy):**

- **Signal derivation + liveness.** From the authored elements, **auto-create** the Signals
  their boundaries pin (`exterior`/`ground`/`solar` singletons; one `adjacent` per named room),
  and **garbage-collect** any signal no live element references (spec 15 liveness invariant).
- **The grouping function:** `group(elements, treatments) -> list[DerivedModule]`, emitting
  **one module per distinct `(treatment-module-type, signal)`**. Two south windows → one
  `SolarGain[G_sol_S]`; south + west → two; two partitions→kitchen → one `DirectLoss[T_kitchen]`.
  A module spends the **summed** channel budgets of its claimed elements into its prior (I4).
- **Keep the exactly-once / completeness check (I3)** as an internal assertion on the rule's
  output — a double-count or unclaimed channel is now an **engine bug** surfaced as a `problem`,
  never user error.
- **Heavy/light treatment** drives the only branch: a heavy wall with `treatment=simple_loss`
  routes to `DirectLoss[T_ext]` instead of `HeavyWall[T_ext]`.

**Acceptance (headless):** the canonical-room table in [§D5](#d5--validation--usability-harness)
passes — derived module sets equal what physics says, across all four rooms; the treatment flip
swaps `HeavyWall[T_ext]`↔`DirectLoss[T_ext]`; no `problems` on any clean room.

---

## D3 — Derived-module API + assembly projection

**Context:** spec 30 → "Direction change" deltas. Depends on D1 (shapes) + D2 (rule).

**Scope (FastAPI, `src/thnodes/api/`):**

- **Retire** `POST/DELETE /modules` and `PUT …/routing`. Modules are no longer authored.
- **`GET /document`** returns `signals: [...]` alongside `elements`; `modules` is the
  **derived** read-only list from D2.
- **Element CRUD side-effects:** a boundary edit (`PATCH /elements`) may auto-create / GC
  Signals (D2). The mutation still returns the element; the re-pull invariant (spec 10)
  refreshes derived signals + modules.
- **`GET /assembly`** gains `required_signals` (the input list the right column renders): the
  set of Signals the derived modules demand, each with role/kind/meta. Keep `ownership`,
  `parameters`, `graph`, `problems` shapes; `problems` now means an engine bug, not user error.

**Acceptance (headless, `TestClient`):** author the caravan via element CRUD; `/document` shows
the derived modules + auto-created Signals; `/assembly.required_signals` lists exactly
`{T_ext, G_sol_S}`; no module/routing endpoints remain.

---

## D4 — Element-form authoring UI

**Context:** spec 20 (the `[§15-pending]` sections), spec 10 (the store/mutation invariant —
unchanged). Depends on the D3 contract (build against fixtures first, integrate last).

**Scope (Svelte + DaisyUI, `frontend/`):**

- **Element cards become the only authoring surface:** per-type forms (driven by the registry)
  with **boundary field(s)** (orientation / adjacent-room / ground) and, for heavy walls, a
  **treatment toggle**. No "add module" form, no routing checkboxes.
- **Topology + module list go read-only** — one branch per `(treatment, signal)`, labelled by
  its boundary signal (`ModuleType[Signal]` notation). The server SVG stays.
- **Inputs panel generated from `/assembly.required_signals`** — one entry per required Signal
  (right column). Ad-hoc series / scenario per signal for now (no data-source binding).
- **Ownership matrix → collapsible diagnostic only**, auto-expanding on `problems`.
- (Carry the open spec-20 item: every shown value carries its SI unit, from one shared map.)

**Acceptance:** author the caravan and a 2-orientation / 2-adjacent-room room entirely through
element forms; the derived topology + inputs panel update with no routing UI; matrix stays
collapsed and quiet on clean rooms.

---

## D5 — Validation & usability harness  *(the conviction artifact)*

**Context:** the canonical rooms; this is the headless proof the data model is right. Consumes
D2 directly — **can start as soon as D2 has a first version**, in parallel with D3/D4.

Extend `notebooks/case_*.py` (or add `case_grouping.py`): author each canonical room **in plain
Python through the new model** (elements + boundaries + treatments), run the grouping rule, and
**assert the derived module set**:

| room                        | author                                          | derived modules (must equal)                                |
| --------------------------- | ----------------------------------------------- | ----------------------------------------------------------- |
| caravan (all-light)         | light walls + S window + IndoorMass             | `RoomMass`, `DirectLoss[T_ext]`, `SolarGain[G_sol_S]`       |
| two adjacent rooms          | + 2 partitions→kitchen, 1 partition→hallway     | `+ DirectLoss[T_kitchen]`, `+ DirectLoss[T_hallway]`        |
| two glazing orientations    | S window + W window                             | `SolarGain[G_sol_S]`, `SolarGain[G_sol_W]` (two, not one)   |
| heavy wall + treatment flip | heavy S wall; toggle simple-loss                | `HeavyWall[T_ext]` ↔ `DirectLoss[T_ext]`                    |

**The usability test is step 1 itself:** if authoring a room (especially the adjacent-room and
multi-orientation cases) is awkward or ambiguous in the element vocabulary, it surfaces here —
that feedback loops back into D1's field design. **This phase is "done" when these rooms are
natural to express and the derived modules are exactly right.**

---

## Phase D — explicitly out of scope (deferred; named so they don't creep in)

- **The fit (Steps 2–3)** — untouched; resumes after D.
- **Signal → real data-source binding** (InfluxDB / CSV / derived chains) — the Signal stays
  binding-agnostic (spec 15). Only ad-hoc `/simulate` series for now.
- **Solar POA accuracy / tilt / roofs** — `G_sol_<orient>` carries orientation in `meta`; the
  transposition stays today's simple cosine model (`solar.py`).
- **Heavy-wall sol-air activation** — still the `_T_sol_air = T_ext` deferral (see
  [§Known placeholders](#known-placeholders-to-revisit)). Don't fix it in Phase D.

---

# Deferred — the fit engine (Steps 2–3)

**Do not start until Phase D closes.** Preserved here verbatim-in-spirit from the prior plan;
the data model Phase D produces is what these consume. Full detail in `docs/roadmap.md`.

## Step 2 — Differentiable Kalman + NUTS posterior (twin experiment)

Sample the full posterior `p(θ|y)` from synthetic data; show it covers truth and degrades
honestly (wide/ridged) when collinear. JAX 2-state LTI Kalman (`jax.scipy.linalg.expm`,
`lax.scan`), prediction-error likelihood, log-normal priors sampled in `log θ`, NumPyro NUTS,
ArviZ diagnostics. Validate with the caravan / heavy-wall / collinear twin experiments + a
calibration check (X% CI covers truth ~X% of the time). The collinear case is the prize: honest
width, still covers truth, and the Step-1 lens predicted it.

## Step 3 — Honesty diagnostics

Prior-vs-posterior movement (in `σ_log`), pairwise corner plot (the ridge), sampler health
(`r_hat`/ESS/divergences), innovation whiteness gate (ACF + cumulated periodogram). ArviZ
throughout.

## Step 4b — Fit view ③

After Steps 2–3: surface the posterior, prior-vs-posterior, corner plot, sampler health; the
**study** abstraction (one identification per data time-range) lands here as the additive
`/api/models/{id}/studies/{sid}/…` nesting. Out of scope until then.

## Side quest — CTSM-R oracle (offline, one-time)

After Step 2 works on synthetic data: reproduce the Bacher & Madsen FlexHouse fit in R once,
confirm the Python Kalman likelihood matches. Never enters the deploy.

---

# Done ledger

Compressed history of closed work (full prose lived in earlier revisions of this file + the
specs). Treat the specs as the source of truth for *what these do*; this is just the "it's
built" record.

- **Step 0 — assembler + forward sim (CLOSED).** `channels.py`, `elements.py`, `forms.py`
  (the four flux forms), `solar.py` (cosine-POA placeholder), `assembler.py` (route cells,
  exactly-once assertion, star ODE), `simulate.py` (`solve_ivp`). Caravan + heavy-wall rooms
  assemble; double-count raises; heavy model lags caravan; solar-pulse path tested; happy path
  warning-free; validation notebook renders.
- **Step 1 — identifiability lens (CLOSED).** `identifiability.py`: poles→τ bands, band-overlap,
  broadband **non-constant-input** excitation + **Pearson-r** collinearity (the frequency-point
  check was dropped as wrong for integrating thermal nodes), per-param
  resolvable/borderline/prior_dominated verdict. 21 tests green; case notebook renders verdicts.
- **Step 4a engine additions (CLOSED).** Non-raising assembly (`problems[]`), type **registry**,
  per-parameter **contributions** (`System.parameter_contributions()`).
- **Step 4a app (BUILT, old model).** FastAPI (`src/thnodes/api/`) + Svelte (`frontend/`);
  `/assembly` projection feeding all views; `/simulate`, `/identifiability`, `/topology.svg`;
  multi-model local persistence + home page; server-rendered schemdraw SVG. **Authors via the
  routing matrix — superseded by Phase D.**

---

# Known placeholders to revisit

- **Heavy-wall sol-air:** `forward_sim` uses `_T_sol_air = T_ext`, so the heavy wall's
  `SOLAR_OPAQUE` budget is owned but inactive in the dynamics. Finish with `pvlib` POA
  (`T_sa = T_ext + α·G_poa/h_se`).
- **Sol-air on light walls** (Step-0 deferral; un-deferral = Plan A): `OuterWall.channels()`
  should always emit `SOLAR_OPAQUE`; the light-wall loss module adds a **memoryless** solar
  term with effective area `α·A·(U/h_se)` per orientation (equivalently drive conduction off
  `T_sa`). Currently light walls drop the channel entirely (Plan B) — wrong long-term for
  thin/metal skins (the caravan). See proposal §"Sol-air on a light opaque wall".
- **`solar_boundary`:** cosine-projection placeholder → proper 8-orientation (+tilt) POA model;
  per-`G_sol_<orient>` Signal `meta` carries orientation/tilt for this.
- **Band-overlap threshold (~1 decade in τ):** empirical; pin down once real fits run.
- **`IndoorMass` vs `HeavyWall` both-present:** band rule says ≤1 node per band; the lens must
  flag the borderline case.
- **Signal data-source binding:** the whole future layer (InfluxDB/CSV/derived) — Signal kept
  binding-agnostic so it lands without a migration (spec 15 open questions).
