# thnodes Roadmap

Sequencing for building and validating the engine described in `app_proposal.md`.

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
standard inverse-problem machinery) — it is the **authoring vocabulary** (elements → channels →
modules) and the **"make the mapping visible"** routing matrix. Those concepts can only be
validated by *using* them, and Streamlit's widget model fights the routing-matrix + graph
editing hard enough that prototyping there would push us toward the wrong architecture. Steps
0–1 already produce everything this UI needs (assembled `System`, `ownership_map()`, the
identifiability report, forward sim) — so the authoring UI is buildable now and does **not**
depend on the fit.

What this changes:
- **Step 4 splits.** Step 4a = authoring + topology + identifiability UI (now). Step 4b = the
  fit view ③ (after Steps 2–3 land). The fit view simply does not exist in 4a.
- **Steps 2–3 still happen** — they're deferred, not dropped. The central bet is still the
  central bet; we're just validating the *novel UX* first while the engine for it already exists.
- **The Golden Rule "no FastAPI/Svelte until Step 4" is honored in spirit** — this *is* Step 4
  work, reordered. The engine (Steps 0–1) stays pure NumPy; FastAPI/Svelte are a layer on top,
  never imported by the physics.

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

### Step 4a — Authoring + topology + identifiability UI (build now)

Validates the novel UX (element/channel/module vocabulary + the routing matrix) against the
Steps 0–1 engine. **Detailed, parallelizable spec lives in `docs/TODO.md` → "Step 4a".** Summary:

- FastAPI backend: in-memory `dict[model_id, RoomDoc]`; CRUD on elements/modules/routing;
  `GET /models/{id}/assembly` (the one projection feeding all views — ownership matrix,
  parameter table + per-element contributions, graph, problems); `POST …/simulate`;
  `GET …/identifiability`; `GET …/topology.svg`.
- Engine additions (headless, pure NumPy): non-raising assembly (`problems[]` instead of
  raise/warn), a type **registry** (element/module schemas for data-driven forms), and surfacing
  per-parameter **contributions** (which element/channel budget fed each prior — already computed
  inside `build()`, currently discarded).
- Svelte + DaisyUI: element cards (add/delete/edit + computed channel budgets), module graph
  (add/remove modules, wire module→elements, problems highlighted), parameter table (priors +
  per-element contribution breakdown).

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
