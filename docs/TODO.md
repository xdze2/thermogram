# thnodes — Implementation TODO

**Audience: a fresh model session with no prior context.** This file is self-contained
enough to start work, but you **must** read these first:

0. `docs/specs/00_overview.md` — the authoritative target-state spec set and reading order.
   Start here; the specs are what code is checked against.
1. `docs/background/app_proposal.md` — the full design rationale. Non-negotiable concepts:
   star topology, the (element, channel) ownership model, the four flux forms, the band rule,
   log-normal priors.
2. `docs/roadmap.md` — the sequencing and *why* (validate the engine with synthetic twin
   experiments before building any UI).
3. `docs/background/reading_note_bacher_madsen_2011.md` — the fit method (Kalman
   prediction-error likelihood, not least-squares).

**Golden rules**
- `uv`-managed. **No FastAPI / Svelte until Step 4.** *(Amended 2026-06: the authoring/visualization
  half of Step 4 — "Step 4a" — is pulled ahead of the fit (Steps 2–3) to validate the novel UX
  early. This is still Step 4 work, reordered, not new work before it. The engine stays pure NumPy;
  FastAPI/Svelte remain a layer on top that the physics never imports. See `docs/roadmap.md` →
  "Sequencing amendment" and "Step 4a" below.)*
- **The fit target is the FULL POSTERIOR, sampled with NUTS — not a MAP point.** The data is
  collinear; the posterior is degenerate (ridges); its *shape* is the identifiability answer.
  This dictates the backend: NUTS needs gradients → the Kalman log-likelihood must be
  differentiable → **JAX** Kalman + **NumPyro** sampler. (This supersedes any "NumPy Kalman"
  phrasing in older notes, which assumed MAP.)
- The Kalman filter stays **hand-rolled (~30 lines)** — JAX is the array backend, **NOT** a
  black-box state-space/Kalman library (`filterpy`, `statsmodels`, `pykalman` are all out).
- Keep JAX **contained to the fit core (Steps 2–3)**. Steps 0–1 (assembler, forward sim,
  identifiability lens) and the simulation toy stay plain NumPy — they must not import JAX.
- **CTSM-R is a validation oracle only — never a runtime/import dependency.**
- Validate with **synthetic data** (known ground truth) before any real data. With a posterior,
  "validate" means *the posterior covers the truth and is calibrated*, not "the point matches".
- The canonical test cases (caravan / heavy-wall / collinear) run **headless** — they are
  the test suite.
- Work the steps **in order**. Each step has acceptance criteria; do not advance until they
  pass.
- Keep modules as **star branches**: one terminal is always `T_room`, the other is a boundary
  signal; hidden states are private to the owning module.

---

## Step 0 — Project scaffold + Assembler + forward simulation

Goal: assemble a star RC ODE from elements/modules and integrate it forward. **No fitting.**

### 0.1 — Scaffold
- `uv init`; package `src/thnodes/`.
- Steps 0–1 deps: `numpy`, `scipy`, `matplotlib`, `pytest`.
- Steps 2–3 add: `jax`, `numpyro`, `arviz`. (`pvlib` only with real data, Step 4-ish.)
- The assembler must emit a **backend-agnostic** linear-system description (`A`/`B`/`C`
  builders as plain arrays / pure functions) so the JAX Kalman can consume it without the
  assembler itself importing JAX.
- Layout:
  ```
  src/thnodes/
    materials.py      # materials_db: name -> (rho, lambda, cp); is_heavy(rho>500)
    channels.py       # Channel enum, Budget dataclass
    elements.py       # EnvelopeElement + subclasses; .channels() -> {Channel: Budget}
    forms.py          # the 4 flux forms (Conductance, SolarGain, DelayedConductance, SourceFlux)
    modules.py        # named modules (RoomMass, DirectLoss, ...) wrapping forms + derive_priors
    solar.py          # solar_boundary(orientation, eff_area, weather) -> flux signal
    assembler.py      # Assembler: route cells, assert exactly-once, build ODE
    simulate.py       # forward_sim(system, signals, x0, dt) -> states over time
  tests/
  notebooks/          # or scripts/ — validation harness
  ```

### 0.2 — Channels & budgets (`channels.py`)
- `Channel(Enum)`: `CONDUCTION, SOLAR_TRANSMISSION, SOLAR_OPAQUE, STORAGE`.
- `Budget` dataclass: `UA, shgcA, alphaA, C` (all `float | None`).

### 0.3 — Elements (`elements.py`)
- `EnvelopeElement.channels() -> dict[Channel, Budget]`, conserved budgets computed **once**,
  model-agnostic. ISO 6946 for `U` (sum layer resistances + surface resistances `Rsi/Rse`).
- Subclasses: `OuterWall(orientation, layers)`, `Window(orientation, area, U, shgc)`,
  `Floor(boundary∈{ground,adjacent,exposed}, layers)`, `Partition(layers)`,
  `IndoorMass(C)`, `HeatSource`.
- `STORAGE.C` = sum of `rho*cp*thickness*area` over **heavy layers only** (rho>500).
- Keep ISO surface resistances as module-level constants (`Rsi≈0.13`, `Rse≈0.04`).

### 0.4 — The four flux forms (`forms.py`)
Each exposes `flux_room(params, signals, states) -> float` and (if stateful)
`state_ode(...) -> dict[state_name, float]`. Signature convention: `params` dict,
`signals` dict of callables/arrays at time t, `states` dict.

| Form                 | flux into T_room           | private state | ODE                                                             |
| -------------------- | -------------------------- | ------------- | -------------------------------------------------------------- |
| `Conductance`        | `H*(T_bnd - T_room)`       | —             | —                                                              |
| `SolarGain`          | `aA * G` (into target node)| —             | —                                                              |
| `DelayedConductance` | `H_in*(T_node - T_room)`   | `T_node`      | `C*dT_node = H_out*(T_bnd - T_node) - H_in*(T_node - T_room)`  |
| `SourceFlux`         | `Q(t)`                     | —             | —                                                              |

### 0.5 — solar_boundary (`solar.py`)
- `solar_boundary(orientation, eff_area, weather)` → flux time series.
- 8 orientations: `S, SE, SW, E, W, NE, NW, N`. Project GHI/DHI/DNI (or a provided POA) onto
  the plane. **For Step 0 a simple cosine-projection placeholder is acceptable** — flag it
  `# TODO proper POA` and move on; do not block the engine on irradiance modelling.
- Called by `SolarGain` (injects into `T_room`) and by `HeavyWall` (injects into its own
  outer node as the sol-air boundary). Same helper, two attachment points — this is the
  star-topology factoring; do not make solar a node-attaching module.

### 0.6 — Modules (`modules.py`)
Implement the **canonical catalogue** from `background/app_proposal.md` (§Module catalogue). Minimum for
Step 0: `RoomMass`, `DirectLoss`, `SolarGain`, `HeavyWall`. Each module:
- declares `params`, `signals` (boundary only), `private_states`, `owns: list[Channel]`;
- `derive_priors(cells) -> {param: (mu_log, sigma_log)}` by **spending** claimed budgets
  (see Step 2 for the log-normal detail; for Step 0 a placeholder prior dict is fine, priors
  are unused until the fit).
- `HeavyWall` splits one conserved `U·A` into `H_out`/`H_in` by the `Rse/Rsi` ratio around
  the element's `C` — it does **not** invent two independent conductances.

### 0.7 — Assembler (`assembler.py`)
1. For each element, get `channels()`.
2. Route each `(element, channel)` cell to its owning module per the ownership rule.
3. **Assert exactly-once per cell** — raise on double-count (two modules claiming the same
   `(element, channel)`).
4. Collect `private_states` → state-vector order (room state last, by convention).
5. Build RHS: `dT_room/dt = (Σ flux_room) / C_room`; append each module's `state_ode`.
6. Collect `params`, boundary `signals`; warn on missing signals.
Return a `System` object exposing `rhs(t, x, signals, params)`, plus `state_names`,
`param_names`, `signal_names`.

### 0.8 — forward_sim (`simulate.py`)
- Fixed-step integrator (RK4 or `scipy.integrate.solve_ivp`). Hourly default `dt`.
- Inputs: `System`, signal arrays, `x0`, parameter values. Output: state trajectories.

### ✅ Step 0 acceptance
- `pytest`: assembling the **caravan** (`RoomMass + DirectLoss + SolarGain`, state `[T_room]`)
  and the **current-default** (`RoomMass + DirectLoss + HeavyWall + SolarGain`, state
  `[T_wall, T_room]`) succeeds; param/state/signal lists match the proposal's examples.
- A deliberate double-count (two modules claiming one `(element, CONDUCTION)` cell) raises at
  assembly time.
- A notebook/script plots step response: a `+10°C` step in `T_ext` and a daytime solar pulse
  produce monotone, settling `T_room`; the heavy model lags the caravan (visible thermal
  inertia). Eyeball-sane is the bar here.

### 🔧 Step 0 — closeout (DEFERRED — pick this up next)

Step 0's spine is done: both reference topologies assemble, the double-count guard raises,
`forward_sim` runs, the heavy model lags the caravan, 8 tests green. **But four loose ends stand
between "tests pass" and "Step 0 honestly closed." Do these before starting Step 1.**

1. **Add a solar-pulse test (the untested half of the step-response criterion).**
   Current tests only exercise the `T_ext` step with `G_sol = 0` everywhere — so the
   `SolarGainModule` path (reads `G_sol` → flux into `T_room`) is *assembled but never fired*.
   Add a test: flat `T_ext` (no conduction gradient), a daytime `G_sol` bump (e.g. a half-period
   sinusoid or boxcar over hours 8–18), assert `T_room` rises during the pulse and relaxes after.
   This is the one path that could be silently broken; it must be exercised.

2. **Resolve `SOLAR_OPAQUE`-on-light-walls (a warning fires on the caravan happy path).**
   `OuterWall.channels()` always emits `SOLAR_OPAQUE`, but `DirectLoss` only owns `CONDUCTION`,
   so a light wall's `SOLAR_OPAQUE` is unclaimed → `UserWarning` on every green-path build.
   **Decision (already made): DEFER, don't implement sol-air-on-light-walls now.** Implement the
   deferral cleanly: suppress this specific warning for light exterior walls *with a tracked
   note* (don't leave a warning firing on the happy path — it trains everyone to ignore
   warnings). The proper fix (later, with `pvlib`): `DirectLoss` consumes `SOLAR_OPAQUE` by
   shifting its reference `T_ext → T_sa` via `solar_boundary` (see proposal §"Solar is a reusable
   boundary helper").

3. **Replace the `_T_sol_air` silent fallback in `simulate.py` with an explicit deferral.**
   `forward_sim` currently injects `_T_sol_air = T_ext` "when alphaA/UA unknown at sim level."
   Consequence: `HeavyWall`'s sol-air boundary is *just `T_ext`* — the `SOLAR_OPAQUE` budget the
   heavy wall owns is computed but **never enters the dynamics** (dead path in simulation). For
   Step 0 this is acceptable (the criterion only needs inertia, which works), but it must be
   **named as a deferral, not a silent `if`-block that looks like it works.** Add an explicit
   `# DEFERRED (Step 0): heavy-wall sol-air uses T_ext only; SOLAR_OPAQUE not yet active —
   finish with pvlib POA` comment and a line in this TODO's "Known placeholders" section.

4. **Write the validation notebook/script (the eyeball artifact).**
   `notebooks/step0_validation.py` (or `.ipynb`) producing the plots a human actually looks at:
   (a) `T_ext` +10 °C step → caravan vs heavy `T_room` overlay (shows the lag); (b) solar pulse
   → `T_room` rise/relax. The automated tests assert the numbers; this is the "curves look
   physically right" check the acceptance criterion explicitly asks for. For a physics engine the
   plot *is* the point.

**Done when:** items 1–4 complete, `pytest` green **with no warnings on the happy path**, and the
notebook renders both plots looking physically sane. Then Step 0 is closed — start Step 1.

---

## Step 1 — Identifiability lens (standalone, no fit)

Goal: predict, **before fitting**, which parameters the data can resolve.

- `bands_from_system(System, prior_means) -> list[tau]`: build `A` at prior-mean params,
  `tau_k = -1/Re(eig(A))`. (Assemble `A` from the linear ODE; the star system is LTI.)
- `band_overlap(taus) -> list[pairs]`: flag node pairs within ~1 decade in `tau`
  (threshold = **placeholder constant**, comment it as such; pin down empirically later).
- `input_excitation(signals) -> per-band power + cross-coherence`: periodogram of each
  boundary signal; magnitude-squared coherence between pairs (`scipy.signal.welch` /
  `coherence`). Report, per band: (a) is there spectral power; (b) are driving signals
  mutually correlated.
- `identifiability_report(System, prior_means, signals) -> {param: status}` with
  `status ∈ {resolvable, borderline, prior_dominated}` + a human-readable reason.

### ✅ Step 1 acceptance (test against known answers)
- A system with two same-band nodes → `band_overlap` flags them.
- Synthesized **correlated** `T_ext`/`G_sol` (e.g. `G = a*T_ext + noise`) → high coherence
  flagged; the two modules' params marked `borderline/prior_dominated`.
- A node whose boundary signal has no spectral power in its band → `prior_dominated`.

### ✅ Step 1 — closeout (RESOLVED)

All four closeout concerns are addressed; 21 tests green with no warnings; the case notebook
renders the verdicts side by side.

1. **[CORRECTNESS — the big one] Pole-frequency vs excitation-frequency mismatch — RESOLVED by
   dropping the frequency-point-check entirely.** The original `input_excitation` asked "is there
   spectral power *at* the pole frequency `f_band = 1/(2πτ)`?" — wrong for an integrating thermal
   node, which low-passes diurnal forcing that sits ~10× *above* its own pole. Rather than chase
   the right frequency window (power "at or above" the pole, or a transfer-function `|H(jω)|`
   sweep), the lens was **re-derived to two broadband metrics that are τ-independent**:
   - `has_power` = "is the boundary signal non-constant" (`std > 1e-9`). A constant input carries
     no information about any parameter regardless of τ; a non-constant diurnal input *does* drive
     a slow node (via integration), so band-frequency placement is irrelevant to whether it's
     excited at all.
   - `max_correlation` = max pairwise **broadband Pearson r** among the non-constant boundary
     signals. Collinearity is a property of the *inputs*, not of the node time constant, so it's
     computed once and shared across bands. For passive diurnal data (`T_ext`/`G_sol` co-varying
     all day) this is the metric that actually decides identifiability.
   `f_band` is still computed and stored on `BandExcitation` for **display only** — it no longer
   gates any verdict. This is deliberately the simple model for now; a transfer-function gain
   sweep can replace it later if a case ever needs band-specific excitation, but passive single-
   room data does not. Tests re-tuned accordingly (no signal-tuned-to-the-pole fixtures remain).
   *(Decision recorded here because it diverges from the fix originally sketched above — same
   spirit as the sol-air Plan A/Plan B reconciliation in "Known placeholders".)*

2. **[TEST INTEGRITY] Threshold agreement — RESOLVED.** Verdict and test now agree at
   `_HIGH_CORRELATION_THRESHOLD = 0.7`: `test_step1.py` asserts correlated inputs reach `|r| ≥ 0.7`
   and independent inputs stay `|r| < 0.7`. (The metric is now Pearson `r`, not scipy `coherence`.)

3. **[ROBUSTNESS] Zero-variance guard — RESOLVED.** Constant signals are excluded up front by the
   `std > 1e-9` filter, so no `0/0` / NaN path exists. (Moot now that the metric is `corrcoef`
   over non-constant signals rather than scipy `coherence`.)

4. **[ARTIFACT] RESOLVED.** `notebooks/case_rooms.py` renders the per-parameter identifiability
   report (resolvable / borderline / prior_dominated + reason) across caravan / heavy-wall /
   collinear.

---

## Case notebooks (cross-cutting — orthogonal to the step-by-step tests)

The per-step tests validate each *mechanism* in isolation. The **case notebooks** validate each
*physical scenario* end-to-end — one notebook per canonical room, running the full pipeline on
it. This is the "what does thnodes say about a caravan?" view that the step files scatter.

`notebooks/case_<room>.py` (or `.ipynb`), one per canonical room — **caravan, cellar, current-
default, Earthship** — each doing, top to bottom:

1. **Construct the room in plain Python.** This *is* the usability test (no UI needed): if a room
   is awkward/ambiguous to express in the element vocabulary, it shows here. Stress-tests whether
   `add_module(mod, elements=[...])` is the right authoring API or wants a friendlier `Room`
   builder on top.
2. **Emit the topology schema.** Requires a new **`System.ownership_map()`** accessor exposing
   the assembler's internal `ownership` dict (`(element, channel) → module`) as a first-class
   output. Render it as the (element × channel) table — the same structure the Step-4 routing-
   matrix UI will display, so build the rendering here and port it later. (Also satisfies the
   "make the mapping visible" requirement.)
3. **Forward-sim plots** (the simulation toy ①): `T_room` under a representative scenario for
   that room (e.g. cellar = ground-driven, near-constant; Earthship = solar + berm).
4. **Identifiability report** rendered as a readable per-parameter table
   (resolvable / borderline / prior_dominated + reason). Side-by-side across rooms is what makes
   the lens legible and catches Step-1 concern #1.
5. **(Later, after Step 2)** posterior corner plot + prior-vs-posterior movement on synthetic
   twin data for that room.

These notebooks double as the Step-2 twin-experiment fixtures and the skeleton of the Step-4 UI
(schema rendering + report rendering are exactly what the frontend shows). **Prereq to build:**
add `System.ownership_map()` — small, and it has a real consumer now rather than being
speculative UI plumbing.

---

## Step 2 — Differentiable Kalman + NUTS posterior, validated by twin experiment

Goal: **sample the posterior** `p(θ | y)` from synthetic data; show it covers the truth and
degrades honestly (wide/ridged, not falsely confident) when collinear.

**Why JAX + NumPyro (read before coding):** the deliverable is the full posterior, not a point.
Collinear data → degenerate posterior (ridges between `C_wall`/`H_in`/`H_out`). Only HMC/NUTS
mixes on that; `emcee`-style gradient-free samplers do not. NUTS needs gradients of the
log-posterior → the Kalman log-likelihood must be **differentiable** → write it in JAX, sample
with NumPyro. Hand-rolled (~30 lines), JAX is just the array backend — **not** a Kalman library.

### 2.1 — Discretize (JAX)
- Continuous `dx = A x dt + B u dt + dω`. Discretize to `x_{k+1} = Ad x_k + Bd u_k + w_k`
  via matrix exponential — use **`jax.scipy.linalg.expm`** (van Loan for `Qd`). Observation
  `y_k = C x_k + v_k`, `C` selecting `T_room`.
- Noise: process `Q` (Wiener `dω`, **the key term** — absorbs unmeasured disturbance),
  observation `R` (sensor floor). Both are sampled parameters with their own priors.
- The continuous `A(θ)`/`B(θ)`/`C` come from the Step-0 assembler's backend-agnostic builders;
  evaluate them inside the JAX log-density so gradients flow through to `θ`.

### 2.2 — Kalman filter (~30 lines JAX)
- Standard predict/update for the 2-state LTI system, written with `jax.numpy`; loop with
  `jax.lax.scan` over time (carry = filtered mean/cov). Return per-step innovations
  `e_k = y_k - ŷ_k` and innovation covariances `S_k`.

### 2.3 — Log-likelihood + log-normal prior (the log-density NumPyro samples)
- Prediction-error log-likelihood = `−Σ_k [ 0.5·log|S_k| + 0.5·e_k' S_k⁻¹ e_k ]`
  (prediction-error ML — **not** least-squares on simulation error).
- **Log-normal priors** on positive params: sample `log θ` (unconstrained) — in NumPyro,
  `numpyro.sample(name, dist.Normal(μ_log, σ_log))` then `θ = exp(log θ)`; NumPyro handles the
  transform Jacobian. `σ_log = ln(1.6)` encodes "±60%". `μ_log` from `derive_priors` (budgets).
- Noise priors: `R` tight around sensor floor (~0.1 °C); `Q` weakly-informative/broad.
- `numpyro.factor("kalman_ll", loglik)` adds the Kalman likelihood to the model.

### 2.4 — Sample + the optional MAP smoke test
- `numpyro.infer.MCMC(NUTS(model), ...)`; multiple chains. Optionally init from a MAP mode
  (`numpyro.infer.Predictive` / a JAX optimizer or `scipy.optimize`) — MAP is a smoke test and
  sampler-init only, **not** the deliverable.
- Always report `r_hat`, ESS, divergence count. Divergences clustering on the heavy-wall ridge
  are expected signal, but high counts mean reparameterize (e.g. non-centered) or accept the
  geometry as the identifiability result.

### 2.5 — Twin-experiment harness
- `simulate_truth(topology, true_params, signals, noise) -> y_obs` (Step-0 forward_sim + known
  process/obs noise).
- `sample_posterior(topology, priors, signals, y_obs) -> InferenceData` (ArviZ).
- Compare **posterior vs true**: does the marginal cover the truth? how tight? which params
  trade off (pairwise)?

### ✅ Step 2 acceptance (the central bet — check the posterior, not a point)

| case                         | topology                              | must show                                                            |
| ---------------------------- | ------------------------------------- | -------------------------------------------------------------------- |
| caravan                      | `RoomMass + DirectLoss + SolarGain`   | posterior tight, **covers truth** (1 fast band) — "works at all"      |
| heavy wall, good excitation  | `+ HeavyWall`, large synthetic swings | `C_wall` marginal tightens around truth → buffered node identifiable   |
| heavy wall, collinear inputs | same, correlated `T_ext`/`G_sol`      | posterior wide/ridged, **covers truth**, marginals ≈ prior **AND** Step-1 lens predicted it |

The third row is the prize: honest width (not false confidence), still covers truth, and the
pairwise posterior shows the ridge the lens flagged in advance.

**Calibration check** (do this — it's the real validation of a posterior): run many synthetic
draws; the X% credible interval should contain the true value ~X% of the time. If coverage is
calibrated and the lens predicts the wide cases, the engine is trusted.

---

## Step 3 — Honesty diagnostics (read off the posterior)

- `prior_vs_posterior(idata, prior) -> per-param`: marginal mean shift (in `σ_log`) **and**
  posterior σ vs prior σ — "did the data tighten this, or is the marginal still the prior?"
- Pairwise corner plot (ArviZ): which parameters trade off along a ridge.
- Sampler health: `r_hat`, ESS, divergences — report, never hide.
- `whiteness(innovations) -> {acf_in_bounds, cum_periodogram_ok}`: ACF within ±1.96/√N;
  cumulated periodogram inside Kolmogorov–Smirnov bounds (evaluate at the posterior mean or via
  posterior-predictive). Model-acceptance gate; post-fit mirror of the Step-1 frequency lens.
- Use **ArviZ** throughout (it consumes NumPyro output directly).

### ✅ Step 3 acceptance
- On the caravan twin experiment, `prior_vs_data` shows the well-excited params moved
  significantly; whiteness passes (residuals are white by construction of the synthetic noise).
- On the collinear case, `prior_vs_data` shows the slow-node params barely moved (consistent
  with Step 1's `prior_dominated`).

---

## Step 4a — Authoring + topology + identifiability UI (PULLED AHEAD of Steps 2–3)

> **Sequencing note:** This is Step 4 work reordered ahead of the fit (Steps 2–3), by decision
> recorded in `docs/roadmap.md` → "Sequencing amendment". We validate the *novel UX* (the
> element/channel/module authoring vocabulary + the routing matrix) first, because the engine it
> needs (Steps 0–1) already exists and the fit does not change the authoring layer. The **fit
> view ③ is Step 4b** and is out of scope here. Steps 2–3 are deferred, not dropped.

Goal: a FastAPI + Svelte app that lets a user author a room (elements → modules → routing), see
the **(element × channel) → module ownership matrix**, the **star topology graph**, the
**parameter table with per-element prior contributions**, run the **forward-sim toy**, and read
the **identifiability report** — with no fit. Local, single-user, single-session, server-side
physics.

### Working in parallel — three tracks, one frozen contract

This step is structured so **a backend agent and a frontend agent can work independently** and
in parallel. The enabling artifact is a **frozen API contract** that both code against. Tracks:

- **Track E (Engine) — pure NumPy, no web deps. MUST LAND FIRST (it is the only shared
  dependency).** Small, headless, fully testable without the API.
- **Track B (Backend) — FastAPI over the engine.** Depends on Track E. Codes against the
  contract; testable with `pytest` + `httpx` (TestClient) without any frontend.
- **Track F (Frontend) — Svelte + DaisyUI.** Depends on the *contract only*, **not** on Track B
  running. Built against a **mock server / fixture JSON** of the contract, so it proceeds in
  parallel with B. Integration (point F at real B) is the last sub-step.

**Rule for parallelism:** the contract (§4a.1) is the interface boundary. Once it's frozen, B and
F never need to talk — they meet at the JSON. Any contract change is a coordinated edit to §4a.1
*first*, then both sides adapt. Do not let B or F drift the contract unilaterally.

**Global API conventions (apply to every endpoint):**
- All model-scoped routes are nested under `/api/models/{model_id}/…`. A single model `"default"`
  is auto-created at startup. (Multi-model *address space* now; save/load/list/persistence later —
  see roadmap "Multi-model / multi-study" decision. **Do not** build persistence or a model
  switcher in 4a.)
- **No `study_id` anywhere in 4a.** Leaf endpoints (`/simulate`, `/identifiability`) take their
  signals/data **in the request body**, never from server-side "current data" — this keeps the
  multi-study seam clean for Step 4b without modeling it now.
- IDs are server-assigned opaque strings. Mutations return the affected resource; the frontend
  re-fetches `/assembly` to refresh derived views (no optimistic derived-state on the client).

---

### Track E — Engine additions (pure NumPy, headless, no web deps) — **land first**

These three are the only engine changes 4a needs. Each is independently testable with `pytest`.

- **E1 — Non-raising assembly.** Add an assembly path that **collects problems instead of
  raising/warning**, returning `(System | None, problems: list[Problem])`. Today
  `Assembler.build()` raises `ValueError` on double-count, `warnings.warn`s on unclaimed channels,
  and raises if `RoomMass` is missing. Provide `build(strict=True)` (current behavior, keep it —
  the headless test suite *wants* the raise) and `build(strict=False)` /
  `assemble_report()` that returns as-complete-as-possible a `System` plus structured problems.
  `Problem = {kind, message, cell?: (element_label, channel)}` with
  `kind ∈ {double_count, unclaimed_channel, missing_room_mass, duplicate_state}`. When `RoomMass`
  is missing, `System` may be `None` (no `C_room`) — that's a reported problem, not a crash.
  *Acceptance:* a double-counted room returns a `double_count` problem (not a raise) under
  `strict=False`; the existing strict raise test still passes.

- **E2 — Type registry.** A module-level registry mapping type-name → constructor + a
  JSON-serializable **param schema** for both elements and modules, so the frontend renders
  "add/edit" forms generically instead of hardcoding every type. Shape (suggestion):
  `ELEMENT_TYPES: dict[str, {ctor, fields: [{name, type, default?, options?}]}]` (e.g. `OuterWall`
  → `area:float, orientation:enum[S,SE,…], layers:list[{material:enum, thickness:float}],
  alpha:float`), `MODULE_TYPES: dict[str, {ctor, owns: [channel], params: [str]}]`. Materials enum
  comes from `materials_db`. *Acceptance:* registry round-trips — constructing every element/module
  from its schema defaults succeeds and matches the hand-written constructors.

- **E3 — Surface prior contributions.** Expose, per parameter, **which (element, channel) budget
  fed its prior**. This data already exists inside `build()` as `module_cells`
  (`{module_name: {(element_id, channel): Budget}}`) but is discarded after `derive_priors`. Add a
  `System.parameter_contributions()` (or include in the report) →
  `{param: [{element_label, channel, budget_field, value}]}`. This is the data the parameter
  table's per-element breakdown and the element card's "what this contributes" both read (one is
  the transpose of the other). *Acceptance:* on the heavy-wall room, `C_wall`'s contributions list
  the heavy wall's `STORAGE` budget; `H_ve`'s list the light elements' `CONDUCTION` budgets.

---

### 4a.1 — The frozen API contract (write this doc FIRST, before B or F code)

Produce `docs/specs/30_api.md` (or an OpenAPI/JSON-schema file) — the single source of truth both
tracks code against. It must specify request/response JSON for every endpoint below. **Freeze it
before parallel work starts.** Endpoints:

**Model-scoped CRUD (Track B owns; F consumes):**
```
GET    /api/models/{id}/document        full RoomDoc (elements, modules, routes)
POST   /api/models/{id}/elements        add element {type, fields}        -> {element}
PATCH  /api/models/{id}/elements/{eid}  modify fields                     -> {element}
DELETE /api/models/{id}/elements/{eid}
POST   /api/models/{id}/modules         add module {type}                 -> {module}
DELETE /api/models/{id}/modules/{mid}
PUT    /api/models/{id}/modules/{mid}/routing  {element_ids:[...]}        -> {module}
GET    /api/registry                    ELEMENT_TYPES + MODULE_TYPES + materials (for forms)
```

**The projection endpoint (the heart — feeds all three views):**
```
GET /api/models/{id}/assembly  -> {
  ownership:   [{element_id, element_label, channel, module_id}]   # routing-matrix cells
  parameters:  [{name, module_id, prior:{mu_log, sigma_log},
                 contributions:[{element_id, channel, budget_field, value}]}]   # E3
  states:      [str]            # state_names (T_room last)
  signals:     [str]
  graph:       {nodes:[{id, kind:'room'|'state'|'boundary'}], edges:[{from, to, module_id}]}
  problems:    [{kind, message, cell?}]    # from E1; never 500 on a mid-edit room
}
```

**Physics views (Track B wraps engine; data in request body — no stored "study"):**
```
POST /api/models/{id}/simulate         {signals:{T_ext:[…], G_sol:[…]}, x0:[…], params?, dt?}
                                       -> {t:[…], states:{name:[…]}}   # simulation toy ①②
GET  /api/models/{id}/identifiability  -> {param_status:{name:{status, reason, tau_h, correlation}}}
GET  /api/models/{id}/topology.svg     -> image/svg+xml   (wraps draw.py)
```

*Routing model (decided):* **per-module element lists** — `PUT …/routing {element_ids}`. The
per-(element×channel) ownership is **computed** (`module.owns ∩ element.channels()`) and surfaced
read-only in `/assembly.ownership`; the matrix is a derived view, not a hand-edited primitive.

*Invalid-state model (decided):* **always assemble, report problems.** `GET /assembly` never 500s
on a structurally-incomplete room — it returns partial data + `problems[]`. The UI highlights bad
cells inline. (This is exactly what E1 enables.)

---

### Track B — FastAPI backend (depends on E + contract)

- `src/thnodes/api/` (new). FastAPI app; in-memory `dict[model_id, RoomDoc]` session store;
  `RoomDoc` = `{elements:{id→spec}, modules:{id→spec}, routes:{module_id→[element_ids]}}`.
  Server-assigned IDs. **No persistence** (in-memory only — restart loses state; that's fine for
  4a).
- Implement every endpoint in §4a.1. `/assembly` rebuilds via the **E1 non-raising path** on each
  call (cheap; the room is tiny) and maps engine output → contract JSON.
- Pydantic schemas mirror the E2 registry (generate from it where practical so they can't drift).
- Keep all physics **server-side**; the engine is imported, never reimplemented.
- *Acceptance (headless, no frontend):* `pytest` with FastAPI `TestClient` — author the caravan
  via CRUD calls, `GET /assembly` returns the expected ownership/parameters/graph; a deliberate
  double-count surfaces in `problems[]` (not a 500); `/simulate` on the caravan returns a settling
  `T_room`. Backend is "done" when these pass **without any frontend existing.**

### Track F — Svelte + DaisyUI frontend (depends on contract only)

- Scaffold under `frontend/` (Vite + Svelte + DaisyUI). Build against **mock fixtures** of the
  §4a.1 contract first (commit a `fixtures/` of example `/assembly`, `/registry` JSON), so F does
  **not** block on Track B.
- One shared store hydrated from `GET /assembly`; mutations call CRUD then re-fetch `/assembly`.
- Three views (build in this order — each is independently demoable against fixtures):
  1. **Element cards** — list/add/delete/edit (forms driven by `/registry`); each card shows its
     computed channel budgets + which module-param it feeds (from `parameters[].contributions`).
  2. **Module graph + routing matrix** — the star topology (`graph`) with add/remove modules and
     module→element wiring (`PUT …/routing`); the (element × channel) ownership matrix with
     `problems[]` highlighted on offending cells. *This is the novel "make the mapping visible"
     artifact — the centerpiece.*
  3. **Parameter table** — name, prior (μ_log/σ_log), per-element contribution breakdown; plus the
     **identifiability report** rendered as resolvable/borderline/prior_dominated tags (**label it
     clearly: about *fitting*, not *simulating***). Scenario sliders → `/simulate` → `T_room` plot
     (the simulation toy).
- *Acceptance:* all three views render correctly against the committed fixtures; then the
  integration sub-step points F at a live Track-B server and the same flows work end-to-end.

### ✅ Step 4a acceptance (integration — after E, B, F land)

- Author the **caravan** and the **current-default (heavy-wall)** rooms entirely through the UI
  (no Python) — this *is* the authoring-usability test the case notebooks foreshadowed.
- The ownership matrix matches `System.ownership_map()` for both rooms; the graph shows the star
  with `T_wall` as a private node on the heavy room.
- A deliberate double-count (wire two modules to claim one `(element, CONDUCTION)` cell) shows as a
  highlighted problem in the matrix — **the app does not crash** (E1 + always-assemble contract).
- The parameter table shows `C_wall` fed by the heavy wall's `STORAGE` budget; the identifiability
  report renders the same verdicts the Step-1 case notebook produced, labeled as a *fit* property.
- The forward-sim toy reproduces the Step-0 step-response curves (heavy lags caravan).

### Step 4b — Fit view ③ (deferred to after Steps 2–3)

Out of scope for 4a. Surfaces the posterior (corner plot, prior-vs-posterior movement, sampler
health) and introduces the **study** abstraction (one identification per data time-range) as the
additive `/api/models/{id}/studies/{sid}/…` nesting (see roadmap decision). Do not build in 4a.

---

## Side quest (optional, offline) — CTSM-R oracle

After Step 2 works on synthetic data: reproduce the Bacher & Madsen FlexHouse fit in R once,
offline, and confirm the Python Kalman likelihood matches. Confidence check on the ~30 lines
of Kalman. **Never enters the deploy.**

---

## Known placeholders to revisit (do not silently bake in)
- **Heavy-wall sol-air** (Step 0 deferral): `forward_sim` uses `_T_sol_air = T_ext`, so the
  heavy wall's `SOLAR_OPAQUE` budget is owned but inactive in the dynamics. Finish with the
  `pvlib` POA work (`T_sa = T_ext + α·G_poa/h_se`).
- **Sol-air on light walls** (Step 0 deferral — un-deferral spec below). **Note the code chose
  a different deferral than the original plan and they must be reconciled when un-deferring:**
  - *What Step 0 did (Plan B):* `OuterWall.channels()` only emits `SOLAR_OPAQUE` when
    `C_heavy > 0`, so light walls don't offer the channel at all → no warning, but the physics
    is dropped at the element level. Fine for Step 0; **wrong long-term** (silently zeroes solar
    on thin/metal light walls — see the caravan).
  - *What to do when un-deferring (Plan A — the correct model):*
    1. `OuterWall.channels()` always emits `SOLAR_OPAQUE = Budget(alphaA=α·A)` (drop the
       `C_heavy > 0` gate on that channel).
    2. `DirectLoss` claims **both** `CONDUCTION` and `SOLAR_OPAQUE` of its light walls.
    3. `DirectLoss` adds a **memoryless** solar flux into `T_room`, *not* a new node:
       a `SolarGain`-shaped term with effective area **`α·A·(U/h_se)`** (`h_se ≈ 25 W/m²K`),
       per orientation, via `solar_boundary`. Equivalent to driving the conduction off the
       sol-air temperature `T_sa = T_ext + α·G_poa/h_se`.
    4. Keep `U/h_se` explicit — it *is* the documentation of why insulated walls (`U/h_se≈1%`)
       can ignore this but caravan-skin walls (high `U`, high `α`) cannot.
    See proposal §"Sol-air on a light opaque wall" for the full derivation.
- `solar_boundary`: cosine-projection placeholder → proper 8-orientation POA model.
- Band-overlap threshold (~1 decade in τ): empirical, depends on data length/sampling. Pin
  down once real fits run.
- `IndoorMass` vs `HeavyWall` when both qualify: band rule says ≤1 node per band; the
  identifiability report must flag the borderline both-present case.
- `T_ground` for `HeavySlab`: deferred for the **fit** (open question 3); prescribed scenario
  signal for the **simulation toy** only.
