# Reading Note — Bacher & Madsen (2011)

**Identifying suitable models for the heat dynamics of buildings.** Energy and
Buildings 43(11):1511–1522. DTU (Lyngby). PDF: `docs/biblio/Journal_article_-_2011_-_...pdf`

This is the nearest-neighbour paper to our fit layer (phase 2). North star for
*method*, but with one structural mismatch we must design around (see "What
doesn't transfer").

---

## One-line summary

A **forward-selection procedure** that grows a grey-box RC model from the simplest
feasible topology, adding one capacity/resistance at a time, gated by
**likelihood-ratio tests** and validated by **white-residual checks** (ACF +
cumulated periodogram). Answers "how many C's does the data support?" *from the
data*, not from a heuristic.

---

## How it actually works

- **Grey-box = physics structure + stochastic data model.** The model is a set of
  **stochastic** differential equations (SDEs), eq. 11: `dT = AT dt + BU dt + dω`.
  The `dω` (Wiener) terms are the key — they absorb model error and unmeasured
  disturbances so they don't get smeared into the parameters.
- **Estimation = maximum likelihood via Kalman filter.** Because the model is
  linear-Gaussian, the likelihood (eq. 5) is the product of one-step *predictive*
  densities, computed by a Kalman filter (eq. 6). This is **prediction-error ML**,
  NOT least-squares on simulation error. That distinction is why residuals reach the
  sensor-noise floor (<0.1 °C, Fig. 9) instead of biasing the parameters.
- **No priors.** Pure likelihood, fully data-driven. They can afford this — see below.
- **Model set is a tree, hand-built but systematic.** ~16 named networks in App. A.
  Naming *is* the topology: each letter = one state/capacity (`i`=interior,
  `e`=envelope, `h`=heater, `s`=sensor, `m`=medium), `A`=effective solar areas,
  `Ria`=direct interior↔ambient resistance. Forward selection (Fig. 2) only ever
  tries the *smallest* extensions of the current model.
- **Selection path (Table 1):** `Ti → TiTh → TiTeTh → TiTeThTs → TiTeThTsAe` (stop
  at iteration 5, no extension beats p<5%). The final model's residuals are white
  (ACF in bounds Fig. 10; cumulated periodogram on the diagonal Fig. 11). Remaining
  structure is at high-solar moments — their stated next step is a solar-dependent
  Wiener variance.
- **Software:** CTSM (ref [6] Kristensen & Madsen). Method paper for the estimation:
  ref [7] Kristensen, Madsen & Jørgensen (2004), Automatica 40(2):225–237.

---

## Why their identifiability is so clean — and why ours won't be

**Their secret is experimental design, not clever fitting.** The heat input Φ_h is a
**PRBS** (pseudo-random binary sequence, Fig. 5): broadband (excites all the
building's time-constant bands), known, and *decorrelated from solar/ambient* by
construction. Unoccupied test building (FlexHouse, Risø DTU), controllable electric
heaters. They removed collinearity *at the source* rather than fighting it in the fit.

This is the gold-standard case — and **almost none of it is true for our app.**

---

## What transfers to our fit layer (implement this)

1. **Stochastic state-space + Kalman-filter prediction-error likelihood.** The single
   most valuable idea here. For our *linear* model the Kalman filter is ~30 lines of
   NumPy; ML/MAP is `scipy.optimize.minimize`. Build this first against our existing
   2R2C topology, ML-only, validate with ACF + cumulated periodogram.
2. **Forward selection by likelihood-ratio + white-residual validation.** This is the
   principled, *data-adaptive* replacement for the proposal's "4–5 parameters"
   heuristic. The module catalogue (`FluxModule`s) maps onto the naming-as-topology
   convention: each module ≈ one letter / one state.
3. **Validation diagnostics** (ACF inside bounds, cumulated periodogram on diagonal)
   as the model-acceptance gate.

## What does NOT transfer (where our priors earn their keep)

- **No PRBS.** Our inputs are diurnal-dominant and T_ext/G_sol are *correlated*. The
  FIM will be rank-deficient in exactly the ways Bacher & Madsen never hit. Their
  failure mode ("highest error where solar is high") will be **worse and earlier** for
  us because solar is correlated with the other drivers instead of orthogonal to them.
- **We have even less than they assume.** No PRBS, but also typically **no heating
  time series, no occupancy/usage logs** (windows open? internal gains?). Several of
  their *inputs* are, for us, *unmeasured disturbances*.
- **Therefore: ML → MAP.** Where they use pure likelihood, we must add the ISO 6946
  **prior** term. The prior supplies the curvature the passive, collinear data can't —
  it's not a nicety, it's what makes the fit identifiable at all. (This is the
  Kennedy & O'Hagan / Tarantola direction from the bibliography, fused onto this
  paper's Kalman-ML engine.)

---

## Implication for scope — start with a "constant" room

Given how much input information we lack, the honest first target is a room with
**minimal unmeasured disturbance**: a **garage / buanderie / cellar** — unheated or
weakly/constantly heated, low/no occupancy, no solar-driven behaviour, windows
closed. This is the closest we can get to Bacher & Madsen's controlled conditions
*without* a PRBS: by choosing a room where the missing inputs (heating schedule,
occupancy, window state) are approximately constant or absent, so they don't corrupt
the fit. Walk before running on occupied, solar-driven, behaviourally-noisy rooms.

---

## Implementation decision — don't depend on R

Use **CTSM-R as a validation oracle, not a runtime dependency.** Reproduce their
FlexHouse fit in R once, offline, and check our Python Kalman-likelihood code matches.
Then ship pure Python (NumPy Kalman + `scipy.optimize`). Avoids shipping two runtimes
in the FastAPI deploy; keeps the stack in one language. (`statsmodels` `MLEModel` or
`filterpy` are fallbacks, but a hand-rolled 2-state LTI filter is clearer and we'll
want to understand every line when debugging identifiability.)

---

## Suggested next steps

1. **Phase 2a** — NumPy Kalman prediction-error likelihood for the current fixed 2R2C;
   fit by ML (no prior); validate ACF + cumulated periodogram. Optionally validate
   against CTSM-R on FlexHouse data.
2. **Phase 2b** — add the prior term (ML → MAP) + forward selection over modules,
   likelihood-ratio gated. Report prior-vs-data contribution per parameter (the honest
   "did the data move this number?" diagnostic).
3. Read ref [7] (Kristensen et al. 2004, Automatica) for the estimation method details.
