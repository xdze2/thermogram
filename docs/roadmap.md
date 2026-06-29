# thnodes Roadmap

Sequencing for building and validating the engine described in `app_proposal.md`.

## Guiding principle

The whole design rests on one bet:

> A star-topology RC model with budget-spent log-normal priors can recover known
> parameters from collinear passive data — and when it can't, the identifiability lens
> predicts that **in advance**.

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

## Step 2 — Kalman + MAP, validated by twin experiment

The fit engine itself.

- ~30-line NumPy 2-state LTI Kalman filter.
- Prediction-error likelihood (not least-squares on simulation error).
- Log-normal prior term added to negative log-likelihood (`Σ (logθ−μ)²/2σ²`).
- Process/observation noise priors (`Q`, `R`) — weakly informative, not channel-derived.
- `scipy.optimize.minimize`.

**Validate — twin experiment across canonical cases:**

| case                         | true topology                         | must show                                              |
| ---------------------------- | ------------------------------------- | ------------------------------------------------------ |
| caravan                      | `RoomMass + DirectLoss + SolarGain`   | clean recovery (1 fast band) — the "works at all" base |
| heavy wall, good excitation  | `+ HeavyWall`, big synthetic swings   | recovers `C_wall` → buffered node *is* identifiable    |
| heavy wall, collinear inputs | same topology, correlated `T_ext`/`G` | fit sits near prior **and** Step-1 lens predicted it   |

The third row is the prize: method degrades gracefully **and** the lens called it in advance.
If these agree, the central bet holds.

---

## Step 3 — Honesty diagnostics

Cheap once Step 2 exists; how we read every subsequent fit.

- Prior-vs-data movement per parameter (in `σ_log` units): "did the data move this number?"
- Residual white-noise gate: ACF in bounds + cumulated periodogram on the diagonal
  (the post-fit frequency diagnostic matching Step 1's pre-fit lens).

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

Pure Python (NumPy + `scipy`), `uv`-managed, notebook/script-driven. **No FastAPI, no
frontend** until Step 4. The canonical cases run headless.
