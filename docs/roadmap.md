# thnodes Roadmap

Sequencing for building and validating the engine described in `background/app_proposal.md`
(rationale) and specified in `specs/` (target behavior).

## Guiding principle

The whole design rests on one bet:

> A star-topology RC model with budget-spent log-normal priors yields a **posterior** that
> covers the true parameters of collinear passive data — and when the data can't identify a
> parameter, the posterior says so honestly (a wide marginal / a ridge), and the
> identifiability lens predicts that **in advance**.

The deliverable is the **full posterior** `p(θ | y)`, sampled with NUTS — not a point estimate.
The whole point of this data regime is that the *shape* of the posterior (ridges between the
heavy-wall parameters) is the identifiability answer; a point estimate would hide it.

Everything else (FastAPI, Svelte, schemdraw, element editor) is plumbing around that bet.
So we build whatever **falsifies the bet fastest**, with zero UI. The app earns its place
only after the engine survives validation.

### Sequencing amendment (2026-06 — UI-first for the authoring layer)

We are **pulling the authoring/visualization half of Step 4 ahead of Steps 2–3**, deliberately.
Rationale: the genuinely *novel* part of thnodes is not the fit (the Kalman/NUTS layer is
standard inverse-problem machinery) — it is the **authoring vocabulary** and the
**element → RC-model mapping**. Those concepts can only be validated by *using* them. Steps
0–1 already produce everything this UI needs (assembled `System`, forward sim, the
identifiability report) — so the authoring UI is buildable now and does **not** depend on the
fit.

What this changes:
- **Step 4 splits.** Step 4a = authoring + topology + identifiability UI (now). Step 4b = the
  fit view ③ (after Steps 2–3 land). The fit view simply does not exist in 4a.
- **Steps 2–3 still happen** — they're deferred, not dropped. The central bet is still the
  central bet; we're just validating the *novel UX* first while the engine for it already exists.
- **The Golden Rule "no FastAPI/Svelte until Step 4" is honored in spirit** — this *is* Step 4
  work, reordered. The engine (Steps 0–1) stays pure NumPy; FastAPI/Svelte are a layer on top,
  never imported by the physics.

### Sequencing amendment (2026-06b — **current focus: get the data model right first**)

Building Step 4a surfaced that the original authoring vocabulary (**the generic
element × channel routing matrix**) is *too general* — it re-imports the ill-posed generic
reduction v0.3 exists to avoid (see [`../README.md`](../../README.md) → *Design history*). The
fix is a direction change, now specified in
[`specs/15_signals_and_grouping.md`](specs/15_signals_and_grouping.md): the **Signal (boundary
source) is the grouping key**, modules are **derived** by a hardcoded rule from per-element
boundaries, and channels demote to internal bookkeeping.

> **Decision: the immediate priority is the data model and the element→RC mapping — not
> computation.** We get the *concepts* right (Signals, boundaries, treatments, the grouping
> rule, derived modules) by **prototyping the mapping end to end**, before investing further
> in the fit engine (Steps 2–3) or polishing forward-sim. A wrong data model poisons every
> layer above it; a right one makes the fit a contained add-on.

What this changes:
- **A new phase D (Data-model & mapping) is inserted as the current work**, ahead of Steps 2–3.
  See [Phase D](#phase-d--data-model--elementrc-mapping-current-focus) below.
- **Step 4a is re-scoped onto the signal-grouping model** — the routing-matrix authoring it
  originally described is superseded. The matrix survives only as a diagnostic.
- **Steps 0–1 gain a rule layer.** The assembler still does exactly-once bookkeeping and
  prior derivation, but module *membership* now comes from the grouping rule, not hand-routing.
- **Computation stays deferred.** Forward-sim is "good enough" for prototyping the mapping; the
  fit (Steps 2–3) does not start until the data model is settled and exercised.

### Multi-model / multi-study (decided 2026-06 — adopt the address space, build no machinery)

The app will eventually manage **many models** (save/load/clone rooms) and **many studies**
(one identification per data time-range). Decision on doing this now:

- **Multi-model — adopt the *address space*, not the machinery.** Every model-scoped endpoint is
  `/models/{model_id}/…` from day one, with a single auto-created `default` model; the server
  holds `dict[model_id, RoomDoc]`. This is ~free now and the *only* genuinely expensive future
  retrofit (a bare global room would bake "the one room" into every route/store/URL). **Do not**
  build save/load, persistence, a model list, or a switcher UI yet — that's pure machinery that
  adds nothing to concept validation. Adding it later is *additive* (new routes), touching no
  existing endpoint.
- **Multi-study — design nothing, just don't block it.** A "study" = (model + data time-range +
  resulting posterior) — it models the *fit*, which doesn't exist yet (Steps 2–3). Its shape is
  determined by how the Kalman/NUTS layer consumes data; guessing now guesses at the wrong layer.
  Keep the seam clean by making leaf endpoints (`/simulate`, `/identifiability`) take their data
  **in the request body**, never from an implicit "current data" singleton. Then a study later
  becomes a *named, persisted* version of exactly that payload — an additive nesting
  (`/models/{id}/studies/{sid}/…`), no rewrite. **Do not** add `study_id` anywhere yet.

In one line: **`model_id` in the URL space now; persistence, studies, and their UIs later.**

**Validate with synthetic data first, not real sensor data.** With real data you can never
tell whether a bad fit is the *method's* fault or the *data's* fault — and our data
(collinear, occupancy-corrupted) is exactly the kind that fits badly for *data* reasons.
With synthetic data we control ground truth: assemble a topology, pick true parameters,
simulate `T_room`, add known noise, fit, and check recovery. This **twin experiment**
(① forward sim feeding ③ fit) is the standard validation for inverse problems and directly
exercises the "two uses, one engine" claim.

The canonical cases **are** the test suite — they need no UI to run.

---

## Step 0 — Assembler + forward simulation (no fit)

Build the structural core and the cheap half of the engine.

- `Channel` / `Budget` / `EnvelopeElement.channels()` — conserved budgets computed once.
- The four canonical flux forms (`Conductance`, `SolarGain`, `DelayedConductance`,
  `SourceFlux`).
- `solar_boundary` helper (8-orientation POA → flux), called by `SolarGain` and `HeavyWall`.
- `Assembler`: route (element, channel) cells to modules, **assert exactly-once**, build the
  star ODE, collect params/signals.
- `forward_sim` over the assembled system.

**Validate:** assemble the caravan and current-default 2R2C topologies; plot step response to
a `T_ext` step and a solar pulse; eyeball sane `T_room` dynamics. Test that the exactly-once
channel assertion fires on a deliberate double-count.

*No inversion here — catches assembly bugs early and cheaply.*

---

## Step 1 — Identifiability lens (standalone)

The most novel/risky claim in the design — prove it carries weight before any fit depends
on it.

- Eigenvalues of `A` at prior-mean params → pole time constants → bands.
- Band-overlap detection between modules (~one-decade threshold, *placeholder — pin down
  empirically later*).
- Periodogram + cross-coherence of boundary signals (`T_ext`, `G_sol`, …) per band.
- Output: pre-fit "resolvable / borderline / prior-dominated" report per parameter, with
  reason.

**Validate against known answers:**
- Two same-band nodes → must flag overlap.
- Synthesized correlated `T_ext` / `G_sol` → must flag input collinearity.
- A node with no band excitation → must flag unidentifiable.

---

## Phase D — Data-model & element→RC mapping (CURRENT FOCUS)

**This is the active work.** Goal: validate the *concepts* of
[`specs/15_signals_and_grouping.md`](specs/15_signals_and_grouping.md) by building the
mapping end to end and prototyping with it — **before** any further computation work. We are
getting the data model right, not the numerics.

The phase is broken into **separable workstreams** so they can be picked up independently (each
maps to a sub-agent brief in [`TODO.md`](TODO.md)). The hard sequencing constraint is only:
**D1 (the document/data model) before D2–D4** — everything else parallelizes once the shapes
exist.

- **D1 — Document & registry shapes.** Add the `Signal` resource; add per-element **boundary**
  fields and the **treatment** field; extend the registry with boundary descriptors + treatment
  menus. Drop `routes`/`element_ids` from the document. Pure data-shape work; no physics.
- **D2 — Grouping rule (the heart).** The deterministic `(treatment, signal) → module` rule in
  the assembler. Auto-create/garbage-collect Signals from element boundaries. This is where the
  concept lives or dies; it gets the most prototyping and the most tests.
- **D3 — Derived-module API + assembly projection.** Retire module CRUD/routing endpoints;
  make `/document` return derived modules + signals; add `required_signals` to `/assembly`.
- **D4 — Element-form authoring UI.** Per-element-type forms with boundary/treatment controls;
  read-only derived topology; generated inputs panel; matrix demoted to diagnostic.

**Validate (concept-level, headless first):** build the canonical rooms *through the rule* and
assert the derived module set is what physics says it should be —

| room                        | author                                          | derived modules (must equal)                                   |
| --------------------------- | ----------------------------------------------- | -------------------------------------------------------------- |
| caravan (all-light)         | light walls + S window + IndoorMass             | `RoomMass`, `DirectLoss[T_ext]`, `SolarGain[G_sol_S]`          |
| two adjacent rooms          | + 2 partitions→kitchen, 1 partition→hallway     | `+ DirectLoss[T_kitchen]`, `+ DirectLoss[T_hallway]`           |
| two glazing orientations    | S window + W window                             | `SolarGain[G_sol_S]`, `SolarGain[G_sol_W]` (two, not one)      |
| heavy wall + treatment flip | heavy S wall, toggle simple-loss                | `HeavyWall[T_ext]` flips to `DirectLoss[T_ext]`                |

The prize for this phase: **the same room authored two ways (e.g. one kitchen partition vs.
two) produces exactly the module set a building physicist would draw**, with no routing UI and
no double-counts. When that feels natural to *use*, the data model is right and computation can
resume.

**Explicitly out of scope for Phase D** (deferred, named so they don't creep in):
- The fit (Steps 2–3) — untouched.
- Signal → real **data-source binding** (InfluxDB/CSV) — the Signal stays binding-agnostic
  (see `15`); only ad-hoc `/simulate` series for now.
- Solar POA accuracy / tilt / roofs — `G_sol_<orient>` carries orientation in `meta`; the
  transposition stays today's simple cosine model.

---

## Step 2 — Differentiable Kalman + NUTS posterior, validated by twin experiment

The fit engine itself. **Full posterior, sampled** — not a point estimate.

**Backend decision (do not skip the reasoning):** the posterior geometry from collinear data
is degenerate (ridges between `C_wall`/`H_in`/`H_out`). Only HMC/NUTS mixes on that;
gradient-free samplers (`emcee`) do not. NUTS needs gradients of the log-posterior → the Kalman
log-likelihood must be **differentiable** → write it in **JAX**, sample with **NumPyro**. The
filter stays hand-rolled (~30 lines, "understand every line"); JAX is the array backend, **not**
a black-box Kalman library. This supersedes the earlier "NumPy Kalman" note, which assumed MAP.

- ~30-line **JAX** 2-state LTI Kalman filter (`jax.scipy.linalg.expm` for discretization).
- Prediction-error likelihood (not least-squares on simulation error).
- Log-normal priors on positive params; sample in `log θ` (unconstrained), include the
  transform Jacobian. Process/observation noise (`Q`, `R`) get their own priors.
- **NumPyro NUTS** for sampling; a MAP mode (JAX optimizer / `scipy.optimize`) only as
  sampler-init + smoke test.
- Diagnostics on every run: `r_hat`, ESS, divergence count (divergences on the heavy-wall ridge
  are *expected signal*, not just a bug — but watch them).

**Validate — twin experiment across canonical cases** (truth known → check the *posterior*,
not a point):

| case                         | true topology                         | must show                                                          |
| ---------------------------- | ------------------------------------- | ------------------------------------------------------------------ |
| caravan                      | `RoomMass + DirectLoss + SolarGain`   | posterior tight, **covers truth** (1 fast band) — "works at all"    |
| heavy wall, good excitation  | `+ HeavyWall`, big synthetic swings   | `C_wall` marginal tightens around truth → buffered node identifiable |
| heavy wall, collinear inputs | same topology, correlated `T_ext`/`G` | wide / ridged posterior covering truth, marginals ≈ prior **AND** Step-1 lens predicted it |

The third row is the prize: the posterior is honestly wide (not falsely confident), it still
**covers** the truth, *and* the pairwise posterior shows the ridge the lens flagged in advance.
Calibration check across many synthetic draws: the X% credible interval should contain the true
value ~X% of the time. If that holds, the central bet holds.

---

## Step 3 — Honesty diagnostics

Cheap once Step 2 exists; how we read every subsequent posterior.

- Prior-vs-posterior per parameter: marginal mean shift (in `σ_log`) **and** posterior σ vs
  prior σ — "did the data tighten this, or is the marginal still the prior?"
- Pairwise posterior (corner plot): which parameters trade off along a ridge — the visual the
  point estimate could never give.
- Sampler health: `r_hat`, ESS, divergences (report, don't hide).
- Residual white-noise gate on the innovations (at the posterior mean or posterior-predictive):
  ACF in bounds + cumulated periodogram on the diagonal (post-fit frequency diagnostic matching
  Step 1's pre-fit lens).
- Use **ArviZ** for the posterior diagnostics/plots (it consumes NumPyro output directly).

---

## Step 4 — The app

Split into 4a (authoring/visualization — pulled ahead, see amendment above) and 4b (fit view —
after Steps 2–3). FastAPI backend wrapping the engine; local, single-user, single-session;
server-side physics. Svelte + DaisyUI frontend.

### Step 4a — Authoring + topology + identifiability UI

**Re-scoped (2026-06b) onto the signal-grouping model.** The original routing-matrix authoring
is superseded; the live spec is [Phase D](#phase-d--data-model--elementrc-mapping-current-focus)
+ [`specs/15_signals_and_grouping.md`](specs/15_signals_and_grouping.md). What carries over
unchanged: the FastAPI/Svelte stack, local persistence, multi-model home, the `/assembly`
projection feeding all views, `/simulate`, `/identifiability`, `/topology.svg`, non-raising
assembly, the type registry, and per-parameter contributions. What changes: authoring is
**element forms + boundaries + treatment**, not add-module/route; modules are **derived**.
Detailed, parallelizable briefs live in [`TODO.md`](TODO.md) → Phase D.

### Step 4b — Fit view ③ (after Steps 2–3)

- Surface the posterior, prior-vs-posterior movement, corner plot, sampler health.
- The "study" abstraction (per data time-range) lands here, not in 4a (see amendment).
- Surface the identifiability report alongside; **make clear it is about *fitting*, not
  *simulating*.**

---

## Side quest — CTSM-R oracle (one-time, offline)

Not a gate on progress. After Step 2 works on synthetic data, optionally reproduce the
FlexHouse fit in R once and confirm our Kalman likelihood matches a reference. A confidence
check on the 30 lines of Kalman — **never a runtime dependency.**

---

## Stack for Steps 0–3

`uv`-managed, notebook/script-driven, headless. **No FastAPI / frontend** until Step 4.

- **Step 0–1** (assembler, forward sim, identifiability lens): NumPy + `scipy`. No JAX needed
  yet — keep these in plain NumPy for clarity.
- **Step 2–3** (fit + diagnostics): **JAX** (differentiable Kalman) + **NumPyro** (NUTS) +
  **ArviZ** (diagnostics/plots). `pvlib` only enters with real data (Step 4-ish), quarantined
  in `solar.py`.

Keep the JAX dependency contained to the fit core: the assembler emits a plain description of
the linear system (the `A`/`B`/`C` builders), and the JAX Kalman consumes it. Forms/elements/
assembler stay backend-agnostic NumPy so Steps 0–1 and the simulation toy never import JAX.
