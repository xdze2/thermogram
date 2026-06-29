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

## Step 4 — The app (plumbing)

Only after the engine is trusted.

- FastAPI backend wrapping the engine. Local, single-user, single-session.
- Svelte + DaisyUI frontend: element editor, scenario sliders, plots.
- schemdraw topology rendering (server-side → SVG/PNG).
- Surface the identifiability report in the UI; make clear it is about *fitting*, not
  *simulating*.

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
