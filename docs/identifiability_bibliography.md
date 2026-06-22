# Identifiability & Grey-box RC Fitting — Reading List

Background reading for the fit layer (phase 2): identifying which thermal RC
parameters are distinguishable from data, and how strong physical priors
(ISO 6946 element descriptions) buy identifiability the data alone can't.

> **Confidence flags.** These were assembled from memory and not verified against
> a database. Trust the _concepts and methods_; **verify author/year/venue before
> citing**.
>
> - ✅ high confidence the work exists and is correctly attributed (year may be ±1)
> - ⚠️ medium — right idea/group, details may be off
> - ❓ conceptual pointer — I'm not certain a specific paper matches; treat as a search prompt

---

## The core framing

Our model is **LTI**: `dx/dt = A(θ)x + B(θ)u`, scalar output `T_room`. So
identifiability is a property of the transfer function `G(s;θ) = C(sI−A)⁻¹B` —
a row of SISO transfer functions, one per input channel (T_ext, G_sol, Q_hvac, …).

A parameter is identifiable iff its sensitivity `∂G/∂θ_j` overlaps with input
spectral power. Parseval ties the two standard tools together:

```
F_jk = Σ_t (∂y/∂θ_j)(∂y/∂θ_k)/σ²  =  (1/2πσ²) ∫ (∂G/∂θ_j)(∂G/∂θ_k)* |u(jω)|² dω
```

- **FIM eigen-analysis** = rigorous, model-coupled test → parameter groupings.
- **Frequency response / coherence** = cheap, prior-free diagnostic of _why_.
- **Priors** = add curvature to the posterior → buy rank the data lacks.

Two failure modes, kept distinct throughout the reading:

- **Structural** non-identifiability — `θ → y` rank-deficient for _any_ input (algebra; data can't fix).
- **Practical** non-identifiability — identifiable in principle, but the input doesn't excite it / noise swamps it (more/better data fixes).

---

## 1. Identifiability methods (domain-agnostic)

- ✅ **Brun, Reichert & Künsch (2001)** — _Practical identifiability analysis of
  large environmental simulation models._ Water Resources Research.
  The collinearity-index + sensitivity-ranking method. The reference for turning
  "which parameter group is degenerate" into a computed number + threshold.

- ✅ **Raue et al. (2009)** — _Structural and practical identifiability analysis of
  partially observed dynamical models by exploiting the profile likelihood._
  Bioinformatics. Domain-agnostic. **Preferred over raw FIM** for nonlinear /
  bounded cases — handles "how far can θ_j move before the fit degrades" honestly.
  Read this for rigor.

- ✅ **Bellman & Åström (1970)** — _On structural identifiability._ Mathematical
  Biosciences. Origin of the structural-vs-practical distinction. Short, foundational.

- ✅ **Ljung** — _System Identification: Theory for the User_ (2nd ed., 1999).
  The LTI system-ID bible; the frequency-domain / transfer-function home of all this.

---

## 2. Building-thermal grey-box (closest to our exact problem)

- ✅ **Bacher & Madsen (2011)** — _Identifying suitable models for the heat
  dynamics of buildings._ Energy and Buildings. **Read first.** Forward-selection
  of RC model order (1R1C → multi-C) via likelihood-ratio tests + residual analysis,
  fit as SDEs. Directly answers "how many C's does the data support?"

> - yes, this is the game
> - how many models there are ? are they hand build ?
> - heat input is known, plus tuned to be identifiable, aka decoupled from solar...etc: **non occuped building**
> - no use of prior, but likelihood, is this Least square opti?
> - less then 0.1°C residuals...
> - see ref 6 for software method, aka CTSM-R R tool Box

- ⚠️ **Madsen & Holst (1995)** — earlier DTU grey-box building work; the lineage
  Bacher & Madsen builds on.

- ⚠️ **CTSM-R** (DTU, Continuous-Time Stochastic Modelling, R toolbox) — the software embodiment of the DTU/Lyngby grey-box school. Know it exists. https://ctsm.info/index.html

- ⚠️ **IEA EBC Annex 58 / Annex 71** — full-scale building energy characterization
  from on-site measurements. Community consensus on dynamic data analysis for
  buildings; where the empirical "what's identifiable from real data" wisdom lives.

- ✅ **ISO 13786** — _Thermal performance of building components — Dynamic thermal
  characteristics._ Periodic (diurnal-harmonic) thermal characteristics. Essentially
  our "single-tone identifiability" made into a standard. Pairs with our existing
  ISO 6946 (static U-values) for the dynamic side.

---

## 3. Strong physical priors (the most relevant thread for us)

Priors are how we buy identifiability data can't give. The Bayesian posterior =
likelihood curvature (FIM) + prior curvature; a tight physical prior on a degenerate
direction (e.g. the `H_out/H_in` split) literally adds rank. This is exactly what
ISO 6946 → Gaussian priors already does in `thermal/priors.py`.

- ✅ **Kennedy & O'Hagan (2001)** — _Bayesian calibration of computer models._
  J. Royal Statistical Society B. **The** paper on calibrating physics models with
  priors + a model-discrepancy term. The discrepancy term matters for us: it keeps a
  too-stiff physical prior from being contradicted by reality and blowing up.

- ✅ **Tarantola (2005)** — _Inverse Problem Theory and Methods for Model Parameter
  Estimation._ SIAM. Free PDF from the author. Rigorous home of "MAP = least squares +
  prior" (Tikhonov ⇔ Gaussian prior) — exactly our fit layer.

- ⚠️ **Heo, Choudhary & Augenbroe (2012)** — _Calibration of building energy models
  for retrofit analysis under uncertainty._ Energy and Buildings. Bayesian calibration
  of building energy models with informative priors. Right domain.

**Design takeaway for the fit layer.** With predominantly diurnal forcing each input
channel carries ≈2 numbers (gain + phase at ω*day); a 5–6 parameter model means 2–3
parameters will be **prior-dominated**. That's correct behaviour \_if reported*. The key
output of the fit is **prior→posterior contraction per parameter** — "data-informed" vs
"prior-dominated" — which falls straight out of the identifiability machinery.

---

## 4. LLMs / transformers — what actually changes (mostly: not the core problem)

Identifiability is a property of `θ → output`. No neural machinery un-fuses parameters
whose information isn't in the data — ML _relocates_ the problem, it doesn't dissolve it.
Be skeptical of "deep learning solves identifiability." Where ML genuinely touches us:

- ✅ **Cranmer, Brehmer & Louppe (2020)** — _The frontier of simulation-based
  inference._ PNAS. Amortized/neural Bayesian inference. Speeds up getting the posterior;
  doesn't change what's identifiable (degeneracy shows up as a wide posterior either way).
  Software: **`sbi`** toolbox (Macke group). Transformers increasingly the density estimator.

- ✅ **Raissi, Perdikaris & Karniadakis (2019)** — _Physics-informed neural networks._
  J. Computational Physics. Overkill for a tiny linear ODE, but the philosophy (hard
  physical priors as constraints) matches our instinct.

- ⚠️ **Rackauckas et al. (2020)** — _Universal Differential Equations for Scientific
  Machine Learning._ arXiv. More apt than PINNs: known RC physics + small neural term for
  the _unmodeled_ residual flux. Keeps identifiable physical parameters, absorbs misfit.

- ⚠️ **Time-series foundation models** (TimeGPT; Chronos, Amazon; Moirai) — pretrained
  forecasting transformers. **Conceptual mismatch for us**: anti-parametric (give a
  forecast, not an `H_env` with a credible interval). Wrong layer for an interpretable tool.

- ❓ **LLM → physical prior elicitation** (room description text → prior distribution
  over θ). The genuine LLM fit, and a direct extension of `build_priors`. Not aware of a
  specific published paper in the building-thermal domain — possibly an open gap.

---

## Suggested reading path

1. **Bacher & Madsen 2011** — our exact problem (model-order selection from data).
2. **Brun et al. 2001** + **Raue et al. 2009** — identifiability methods (collinearity, profile likelihood).
3. **Kennedy & O'Hagan 2001** + **Tarantola 2005** — priors as the cure.

The LLM branch is, for _this_ tool, secondary to honest Bayesian RC identification with
physics priors — which the codebase is already pointed at.
