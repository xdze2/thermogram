# thnodes — Implementation TODO

**Audience: a fresh model session with no prior context.** This file is self-contained
enough to start work, but you **must** read these first:

1. `docs/app_proposal.md` — the full design. Non-negotiable concepts: star topology, the
   (element, channel) ownership model, the four flux forms, the band rule, log-normal priors.
2. `docs/roadmap.md` — the sequencing and *why* (validate the engine with synthetic twin
   experiments before building any UI).
3. `docs/biblio/reading_note_bacher_madsen_2011.md` — the fit method (Kalman
   prediction-error likelihood, not least-squares).

**Golden rules**
- Pure Python (NumPy + SciPy), `uv`-managed. **No FastAPI / Svelte until Step 4.**
- **CTSM-R is a validation oracle only — never a runtime/import dependency.**
- Validate with **synthetic data** (known ground truth) before any real data.
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
- `uv init`; package `src/thnodes/`; dev deps: `numpy`, `scipy`, `matplotlib`, `pytest`.
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
Implement the **canonical catalogue** from `app_proposal.md` (§Module catalogue). Minimum for
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

---

## Step 2 — Kalman + MAP (the fit), validated by twin experiment

Goal: recover known parameters from synthetic data; degrade gracefully when collinear.

### 2.1 — Discretize
- Continuous `dx = A x dt + B u dt + dω`. Discretize to `x_{k+1} = Ad x_k + Bd u_k + w_k`
  (matrix exponential / van Loan, or `scipy.linalg.expm`). Observation `y_k = C x_k + v_k`
  with `C` selecting `T_room`.
- Noise: process `Q` (Wiener `dω`, **the key term** — absorbs unmeasured disturbance),
  observation `R` (sensor floor). Both are estimated parameters with their own priors.

### 2.2 — Kalman filter (~30 lines NumPy)
- Standard predict/update for the 2-state LTI system. Return one-step predictive means,
  covariances `S_k`, and innovations `e_k = y_k - ŷ_k`.

### 2.3 — Prediction-error likelihood + log-normal prior (MAP)
- Negative log-likelihood = `Σ_k [ 0.5*log|S_k| + 0.5*e_k' S_k^{-1} e_k ]`
  (prediction-error ML — **not** least-squares on simulation error).
- **Log-normal prior** on all positive physical params: optimize in `log θ`. Prior term
  `Σ (logθ - μ_log)² / (2 σ_log²)`. `σ_log = ln(1.6)` encodes "±60%". `μ_log` from
  `derive_priors` (budget-spent).
- Noise priors: `R` tight around sensor floor (~0.1 °C); `Q` weakly-informative/broad.
- Objective = NLL + prior penalty; minimize with `scipy.optimize.minimize` (L-BFGS-B in
  log-space). Return MAP params + Hessian (for posterior σ).

### 2.4 — Twin-experiment harness
- `simulate_truth(topology, true_params, signals, noise) -> y_obs` (uses Step 0 forward_sim
  + adds known process/obs noise).
- `fit(topology, priors, signals, y_obs) -> MAP params + diagnostics`.
- Compare recovered vs true.

### ✅ Step 2 acceptance (the central bet)

| case                         | topology                              | must show                                              |
| ---------------------------- | ------------------------------------- | ------------------------------------------------------ |
| caravan                      | `RoomMass + DirectLoss + SolarGain`   | clean recovery within prior σ — "works at all" base    |
| heavy wall, good excitation  | `+ HeavyWall`, large synthetic swings | recovers `C_wall` → buffered node *is* identifiable     |
| heavy wall, collinear inputs | same, correlated `T_ext`/`G_sol`      | fit sits near prior **AND** Step-1 lens predicted it    |

The third row is the prize: graceful degradation **and** the lens agreed in advance. If the
two agree, the engine is trusted.

---

## Step 3 — Honesty diagnostics

- `prior_vs_data(map_params, prior, posterior_sigma) -> per-param movement in σ_log units`:
  "did the data move this number, or is it sitting at its prior?"
- `whiteness(innovations) -> {acf_in_bounds: bool, cum_periodogram_ok: bool}`: ACF within
  ±1.96/√N; cumulated periodogram inside Kolmogorov–Smirnov bounds. This is the model-
  acceptance gate and the post-fit mirror of the Step-1 frequency lens.

### ✅ Step 3 acceptance
- On the caravan twin experiment, `prior_vs_data` shows the well-excited params moved
  significantly; whiteness passes (residuals are white by construction of the synthetic noise).
- On the collinear case, `prior_vs_data` shows the slow-node params barely moved (consistent
  with Step 1's `prior_dominated`).

---

## Step 4 — The app (only after Steps 0–3 are trusted)

- FastAPI backend wrapping the engine. Local, single-user, single-session, server-side physics.
- Svelte + DaisyUI: element editor, scenario sliders (the simulation toy ①②), fit view (③).
- schemdraw topology rendering → static SVG/PNG, served by FastAPI.
- Surface the identifiability report; **make explicit it is about fitting, not simulating.**

---

## Side quest (optional, offline) — CTSM-R oracle

After Step 2 works on synthetic data: reproduce the Bacher & Madsen FlexHouse fit in R once,
offline, and confirm the Python Kalman likelihood matches. Confidence check on the ~30 lines
of Kalman. **Never enters the deploy.**

---

## Known placeholders to revisit (do not silently bake in)
- `solar_boundary`: cosine-projection placeholder → proper 8-orientation POA model.
- Band-overlap threshold (~1 decade in τ): empirical, depends on data length/sampling. Pin
  down once real fits run.
- `IndoorMass` vs `HeavyWall` when both qualify: band rule says ≤1 node per band; the
  identifiability report must flag the borderline both-present case.
- `T_ground` for `HeavySlab`: deferred for the **fit** (open question 3); prescribed scenario
  signal for the **simulation toy** only.
