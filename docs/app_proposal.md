# thnodes app Proposal

A small engineering app for

1. **dynamic thermal building simulation** — the user describes a room, inputs weather
   data, and the inside temperature `T_room` is estimated forward in time;
2. **thermal parameter identification** — the thermal parameters of a room are fitted
   from sensor data using Bayesian inference (MAP).

The app has two layers:

- **Physical layer** — a description of a room as **Elements**: outer wall (surface,
  material stack, orientation), windows, floor slab, partitions, indoor mass, heat
  source, …
- **Topology layer** — a minimal RC-equivalent model, assembled from **Modules**,
  inspired by [Bacher & Madsen (2011)](docs/biblio/Journal_article_-_2011_-_Identifying_suitable_models_for_the_heat_dynamics_of_buildings.pdf).
  *Minimal* is not an aesthetic preference: the model must be only as complex as the
  data can identify (see §Identifiability).

We focus on a **single room**: the model predicts `T_room` (Bacher's `Ti`).

---

## Motivation

The current 2R2C model with sol-air input works well for solar-driven, lightweight rooms.
But different buildings have different dominant dynamics:

- A **cave / cellar** is driven by ground coupling and stored mass, not solar input.
- A **caravan** is all-light: fast dynamics, no wall thermal mass to speak of.
- A **passive house** has very low conduction loss and large controlled solar gain.
- An **Earthship** is dominated by an enormous ground-coupled thermal-mass berm behind a
  large south glazing.

Trying to fit a single fixed 2R2C topology to all of these produces prior–fit divergence:
the optimizer compensates by pulling parameters to physically implausible values.

The fix is to make the model **composable**: assemble it from flux modules that match the
actual physics of the building, with priors derived from the physical element description.

### Two uses, one engine

The modular engine serves **two purposes that share all their assembly code**:

```
                    ┌─────────────────────────────────────┐
   Room elements ──▶│  MODULAR RC ENGINE                   │
                    │  modules → state vector + ODE        │
                    │           + params + priors(elements)│
                    └─────────────────────────────────────┘
                         │              │              │
              sample priors        sample priors   observed data
              + integrate          + integrate      + Kalman
                    │              (many draws)         │
                    ▼                   ▼               ▼
            ① single forward     ② MC ensemble    ③ MAP fit
               "what does this      "uncertainty      "what does
                topology do?"        envelope"         data say?"
```

①+② are the **simulation toy** (a Bret-Victor physics toy, season-long forward
simulation). ③ is the **fit** (phase 2, cf. `reading_note_bacher_madsen_2011.md`). They
share the ODE assembly entirely; the simulation half is nearly free given a `forward_sim`
on the assembled system, and it de-risks the engine before any fit is trusted on it.

**Relation to Bacher & Madsen (2011):** we keep their grey-box engine (Kalman
prediction-error likelihood) and white-residual diagnostics, but deliberately **drop their
automatic forward selection** — our passive, collinear, occupancy-corrupted data cannot
support data-driven topology growth. Instead the topology is **assembled from the physical
description**: the user describes the building element by element, and the modules + their
priors follow. Likelihood-ratio is retained for **one** binary choice only — heavy-vs-light
routing of a wall (§Heavy/light routing) — not for open-ended model search.

---

## Core idea: energy balance as a sum of flux modules

The room air energy balance is:

```
C_room · dT_room/dt = Σ Q_i(t)
```

Each module is one term `Q_i` in that sum. A module knows:

- what **parameters** it contributes (free variables for the optimizer / things to sample);
- what **boundary signals** it requires (`T_ext`, `G_sol`, `T_ground`, …);
- what **private hidden state** it owns (an internal temperature node with its own ODE);
- how to **derive its prior** (μ, σ) from the physical element description.

---

## Star topology: modules are two-terminal devices

> **Invariant.** Every `TopologyModule` is a **two-terminal device**. One terminal is
> always `T_room`. The other is a **boundary signal** (`T_ext`, `T_ground`, `T_adj`,
> `G_sol`, `Q_hvac`, …). A module may own **internal** hidden states (e.g. a heavy wall's
> core node), but those nodes are **private to the module** — no other module connects to
> them.

This is the central structural decision. The RC graph is a **star** centred on `T_room`,
not a free network. The consequences are what make the rest of the design coherent:

- **Every hidden state is justified by exactly one module that owns it, driven by exactly
  one boundary.** There are no shared internal nodes — and shared internal nodes are
  precisely the non-identifiable degrees of freedom the data cannot resolve (see
  §Identifiability). Star topology bakes in the maximum complexity collinear data supports.
- A module is therefore a self-contained branch from `T_room` to the outside world. A heavy
  wall is **one branch** that internally carries its mass node *and* its own outer boundary
  condition (T_ext + absorbed sol-air solar). It does not feed, and is not fed by, any other
  module's node.
- The assembler never has to reason about graph connectivity beyond "which boundary does
  this module attach to" — the topology is always a star, so assembly is just collecting
  branches.

What we give up: RC chains where envelope mass → wall surface → room air through *distinct
shared* nodes. We don't want those — they are the unidentifiable internal nodes. Each module
may still have private depth (a multi-node wall), but the depth is owned, not shared.

### Solar is a reusable boundary helper, not a node-attaching module

Strict star topology forbids a free-floating `SolarGain` module that attaches solar flux to
*someone else's* node. So solar is factored as a **reusable computation**, not a module:

```python
def solar_boundary(orientation, effective_area, weather) -> flux_signal:
    """POA irradiance (8-orientation) × effective area → absorbed flux time series."""
```

- **Window transmission** — a `SolarGain` branch calls `solar_boundary` and injects the
  flux **into `T_room`** (its own terminal). Legal: it injects into the room node.
- **Heavy-wall sol-air** — `HeavyWall` calls `solar_boundary` and injects the flux **into
  its own private outer node** as part of that node's boundary condition. Legal: it injects
  into a node the module owns.

Same physics code, two attachment points, both legal because each injects into a node its
owning module controls. The `SOLAR_OPAQUE` budget is therefore **not owned by a separate
module** — it is a budget `HeavyWall` spends on its own outer boundary.

---

## Ownership: the (element, channel) model

The naïve idea "each module pulls the elements it wants" breaks down on shared elements. Two
situations look the same but are physically opposite:

1. **Competing models of the same path** — a heavy-wall R-C-R chain *and* a lumped envelope
   resistance both claiming a south wall's **conduction**. Genuine **double-counting**: the
   wall's U·A enters the energy balance twice. Illegal.
2. **Distinct additive paths through one element** — a south window contributes **both**
   conduction `U·A·(T_ext − T_room)` **and** solar transmission `SHGC·A·G`. Different
   physical channels, both *should* fire. Legitimate.

The resolution: the unit of ownership is not the element but the **(element, channel) pair**.

### Channels

Each element exposes a set of **channels**, each a conserved physical budget computed
**once** from ISO 6946 / material layers:

| Channel              | Budget                           | Offered by                         |
| -------------------- | -------------------------------- | ---------------------------------- |
| `CONDUCTION`         | `U·A`                            | opaque walls, windows, roof, floor |
| `SOLAR_TRANSMISSION` | `SHGC·A`                         | glazing                            |
| `SOLAR_OPAQUE`       | `α·A` (sol-air on outer surface) | opaque exterior elements           |
| `STORAGE`            | `C` of heavy layers (ρ > 500)    | walls/roof/floor with heavy layers |

Keeping `SOLAR_TRANSMISSION` (glazing) separate from `SOLAR_OPAQUE` (sol-air absorptance on
opaque surfaces) honours **one channel = one physical mechanism**, and keeps α out of the
conduction budget.

### The ownership rule

> **Per (element, channel): exactly one module may claim it.**
> **Across channels: an element may be claimed by many modules.**

| case                            | channels                            | resolution                               |
| ------------------------------- | ----------------------------------- | ---------------------------------------- |
| south window                    | `CONDUCTION` + `SOLAR_TRANSMISSION` | different channels → both fire, correct  |
| heavy vs light wall             | same `CONDUCTION` channel           | one owner → a routing choice             |
| ventilation + window conduction | same `CONDUCTION` (to T_ext)        | merged in one module by design           |
| Earthship berm wall             | `CONDUCTION`(ground) + `STORAGE`    | both owned by the heavy-slab/wall module |

Modules **spend** budgets; they never re-invent them. `HeavyWall.derive_priors` does not
independently invent `H_out, H_in` — it *splits the element's single `U·A`* (by inner/outer
surface-resistance ratio) around the element's `C` (STORAGE). Energy and capacity are
conserved by construction, which keeps the per-module prior logic honest and far less bespoke.

The assembler asserts the exactly-once invariant on each channel cell. **Double-counting is a
hard error at assembly time, not a silent bug in the fit.**

### Heavy/light routing — inferred default + override

A wall's `CONDUCTION` channel routes to one of two modules, and *that routing is the topology
choice* (Bacher's "give this wall its own `Te` state, or not"):

- **`DirectLoss`** — lumped memoryless `H`; the wall's `STORAGE` channel (if any) is ignored.
  "Light wall." Adds **no new time-constant band**.
- **`HeavyWall`** — claims the wall's `CONDUCTION` *and* `STORAGE` channels; re-splits the
  U·A into `H_out`/`H_in` around `C`; adds a private `T_wall` state in a **slow band**.
  "Heavy wall."

The default route is **inferred** from materials (`is_heavy`, ρ > 500, in `materials_db.py`),
with an **optional per-element override**. The principled criterion for the override is the
band rule (§Identifiability): route heavy **iff** the wall's mass opens a time-constant band
not already present *and* the data has independent excitation in that band. Likelihood-ratio
between the `DirectLoss` and `HeavyWall` fits is the data-side check on this single decision.

---

## Four canonical flux forms

All physical terms reduce to one of four mathematical forms:

| Form                                    | Class                | Flux into T_room           | Parameters          | Reads channels                | Private state |
| --------------------------------------- | -------------------- | -------------------------- | ------------------- | ----------------------------- | ------------- |
| conductance to a boundary temperature   | `Conductance`        | `H × (T_bnd − T_room)`     | H                   | CONDUCTION                    | —             |
| irradiance-driven source into a node    | `SolarGain`          | `α·A × G` into target node | α·A                 | SOLAR_TRANSMISSION            | —             |
| conductance through a private mass node  | `DelayedConductance` | `H_in × (T_node − T_room)` | H_out, H_in, C_node | CONDUCTION + STORAGE          | T_node        |
| prescribed heat input                   | `SourceFlux`         | `Q(t)`                     | —                   | — (raw signal)                | —             |

The discriminator is **does it have memory?**

- Memoryless → `Conductance`, `SolarGain`, or `SourceFlux`.
- With thermal mass → `DelayedConductance`.

`SolarGain` is kept separate from `SourceFlux` because its prior is structured (SHGC × A per
orientation), whereas `SourceFlux` is a raw measured/prescribed signal with no prior on
magnitude.

**Sol-air on a heavy wall** is *not* a fifth form and *not* a separate module: `HeavyWall`
(a `DelayedConductance`) constructs its outer node's boundary by adding a `solar_boundary`
flux (the `SOLAR_OPAQUE` budget) to `T_ext`. The absorptance enters there, internal to the
module — consistent with star topology.

---

## Module catalogue (canonical)

This is the single authoritative catalogue. Each module is a star branch from `T_room`.

### Always present

| Module     | Class | Reads                   | Prior logic                    |
| ---------- | ----- | ----------------------- | ------------------------------ |
| `RoomMass` | base  | floor area (no channel) | fast lumped mass (see §C_room) |

`RoomMass` *is* the room node: it owns `T_room` and the `C_room` capacitance. Every model
includes it. Its prior is the **fast-band** lumped mass (air + sensor + light furnishings +
wall surface skins) — see §The C_room splitting problem.

### Memoryless branches

| Module          | Class         | Boundary | Channels it owns                          | Prior logic                          |
| --------------- | ------------- | -------- | ----------------------------------------- | ------------------------------------ |
| `DirectLoss`    | `Conductance` | T_ext    | CONDUCTION of light walls + windows + ACH | Σ U×A + 0.34×ACH×V                   |
| `GroundLoss`    | `Conductance` | T_ground | CONDUCTION of light ground-contact floor  | Σ U×A                                |
| `AdjacentLoss`  | `Conductance` | T_adj    | CONDUCTION of partitions                  | Σ U×A                                |
| `SolarGain`     | `SolarGain`   | G_sol    | SOLAR_TRANSMISSION of windows             | Σ SHGC×A per orientation (8-orient.) |
| `InternalGains` | `SourceFlux`  | Q_int    | —                                         | user-supplied constant or schedule   |
| `HVAC`          | `SourceFlux`  | Q_hvac   | —                                         | measured/prescribed signal, no prior |

`DirectLoss` merges window conduction and ACH ventilation: both are `H × (T_ext − T_room)` on
the conduction-to-T_ext channel, so splitting them brings no modelling benefit.

### Branches with a private slow node

| Module       | Class                | Private state | Flux into T_room           | Node ODE                                                                | Channels owned                                      | Boundary signals |
| ------------ | -------------------- | ------------- | -------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------- | ---------------- |
| `HeavyWall`  | `DelayedConductance` | T_wall        | `H_in × (T_wall − T_room)` | `C_wall·Ṫ_wall = H_out×(T_sa − T_wall) − H_in×(T_wall − T_room)`        | CONDUCTION + STORAGE + SOLAR_OPAQUE of heavy ext walls | T_ext, G_sol   |
| `HeavySlab`  | `DelayedConductance` | T_slab        | `H_in × (T_slab − T_room)` | `C_slab·Ṫ_slab = H_out×(T_ground − T_slab) − H_in×(T_slab − T_room)`    | CONDUCTION + STORAGE of heavy ground-contact elems  | T_ground         |
| `IndoorMass` | `DelayedConductance` | T_mass        | `(T_mass − T_room)/R_m`    | `C_m·Ṫ_mass = (T_room − T_mass)/R_m`                                    | STORAGE of interior mass (furniture / exposed slab) | — (internal)     |

`T_sa` is the sol-air boundary (`T_ext` + absorbed solar via `solar_boundary`).

`HeavyWall`, `HeavySlab`, `IndoorMass` are all the same `DelayedConductance` form — they
differ only in their boundary (T_ext+sol-air / T_ground / *no external boundary, purely a
room-coupled buffer*) and which elements feed their prior. `IndoorMass` is the cheapest way
to add a **medium-band** second time constant; for many real rooms (furniture, internal
partitions, an exposed interior slab) it is more physically honest than `HeavyWall`, and it
needs no external signal — only `T_room` itself drives it.

`HeavySlab` is only identifiable if `T_ground` is measured or modeled (Kusuda–Achenbach). For
the **simulation toy** `T_ground` is a prescribed scenario signal; for the **fit** it remains
deferred (open questions).

---

## The C_room splitting problem — and why frequency is the right axis

The room "mass" is not one thing. It is air, the sensor, furniture, and the inner surface
skins of the walls — and these span a **spectrum of time constants**, not a single value:

| mass contribution        | τ (rough) | spectral band |
| ------------------------ | --------- | ------------- |
| air + sensor             | minutes   | **fast**      |
| furniture, surface skins | ~1 hour   | **medium**    |
| heavy wall core          | 10–100 h  | **slow**      |

A single `C_room` lumps fast + medium together. The question "can we split the mass in two?"
has a sharp answer:

> **A mass split is identifiable iff the two pieces live in different time-constant bands.**

Splitting along a band boundary is exactly the heavy-wall / indoor-mass story: `C_room`
(fast) vs a buffered node `C_wall`/`C_m` behind `H_in`/`R_m` (slow/medium). The buffering
resistance **is** the spectral separator — a low-pass between the slow node and the room. The
prior derivation stays a simple **budget split**: partition total thermal mass between the
fast lumped node and the buffered node by *which materials are thermally fast vs slow*
(surface skins vs core), which `materials_db.py` already encodes via ρ and layer depth.

Splitting mass **within the same band** (two furniture-speed nodes) is ill-posed: there is no
flux asymmetry to separate them, so the prior would do 100% of the work and the data nothing.
This is the failure we design out.

This yields the headline design rule:

> **The band rule.** A module may add a private hidden state **only if it introduces a new
> time-constant band** not already present in the model. Two states in the same band are not
> separately identifiable from a single indoor sensor and must be lumped.

The band rule is the physically-grounded replacement for the old "4–5 free parameters"
heuristic, and it grounds the heavy/light routing decision: route heavy **iff** the wall's
mass opens a distinct band.

---

## Identifiability (fit only) — a quantitative frequency lens

This section applies to **③ the fit**. The **simulation toy (①②) has no identifiability
limit** — forward integration needs no inversion, so it can stack as many modules and states
as the physics warrants.

The star topology with private mass nodes is a linear time-invariant (LTI) system. Its
transfer function from each boundary signal to `T_room` has **one pole per state**, and each
pole sits at a node time constant `τ = C/H`. The band rule above is really a statement about
these poles. We make it checkable in three steps, all computable **before** fitting from the
prior means alone.

### 1. Map physical priors → pole bands

From the assembled system `dx = A x dt + B u dt`, the eigenvalues of `A` are the poles
`λ_k = −1/τ_k`. Evaluate `A` at the **prior-mean** parameters (the channel/budget model gives
these directly). This yields the set of time constants the proposed topology *intends* to
resolve, e.g. `{τ_room ≈ 0.5 h, τ_wall ≈ 40 h}`.

### 2. Detect band overlap between modules

Two modules whose poles fall in the **same** band are candidates for non-identifiability.
"Same band" = within ~one decade in τ (a tunable threshold). Overlap is the structural
warning: the topology is asking the data to separate two effects the dynamics blur together.
`IndoorMass` + `HeavyWall` both present is the canonical at-risk pair (medium vs slow — borderline).

### 3. Check input excitation in each band

Structural overlap is necessary but not sufficient for failure — the data also has to **lack
independent excitation** in the contested band. Compute the (cross-)periodogram of the
boundary signals (`T_ext`, `G_sol`, `T_ground`, `Q_hvac`) and ask, per band:

- Is there spectral power at the band's frequency at all? (No power → the node is never
  excited → its `C`/`H` are unidentifiable regardless of overlap.)
- Are the driving signals **mutually correlated** in that band? Our data is diurnal-dominant
  and `T_ext`/`G_sol` are correlated (the Bacher & Madsen "no PRBS" problem). High coherence
  between two boundaries in a band means their respective modules' parameters trade off.

The product of these three is a **pre-fit identifiability report**: for each parameter,
"resolvable / borderline / prior-dominated", with the reason (no band excitation / band
overlap / input collinearity). This is the quantitative form of "modules should encode
orthogonal fluxes": orthogonality is *checkable* as pole separation **plus** input
incoherence in the shared band.

**Frequency domain is the identifiability lens, not the fitter.** Estimation stays in the
time domain (Kalman prediction-error ML/MAP, per the reading note). The cumulated periodogram
of the *residuals* — already the reading note's acceptance gate — is the matching post-fit
frequency diagnostic. We use spectra to *design and warn*, and Kalman to *fit*.

### Practical envelope (consequence, not axiom)

With a single indoor sensor and collinear passive inputs:

- `RoomMass + DirectLoss [+ SolarGain]` — robustly identifiable. The honest day-one fit.
- `+ HeavyWall` **or** `+ IndoorMass` (one buffered node) — borderline; needs long series
  with large swings; expect the prior to carry much of the slow node.
- `HeavyWall` + `HeavySlab` (7 params, 2 ext-driven nodes) — only viable with extra measured
  states; `HeavySlab` additionally needs `T_ground` (deferred).

The UI surfaces the identifiability report and makes clear it is about **fitting**, not
**simulating**.

---

## Prior derivation

All physical parameters are **strictly positive and span orders of magnitude** (`C`, `H`).
Priors are therefore **log-normal**: Gaussian in `log θ`. This (a) puts zero mass on
unphysical negatives, (b) matches the multiplicative nature of engineering uncertainty, and
(c) makes "±60%" well-defined — it is a multiplicative factor `σ_log = ln(1.6)`, not an
additive band. The MAP objective adds `Σ (log θ − μ_log)² / (2 σ_log²)` to the negative
log-likelihood.

Each module derives its prior by **spending its claimed channel budgets** (§Ownership). The
canonical example is `HeavyWall`: one conserved `U·A` is split into `H_out`/`H_in` by the
ISO 6946 inner/outer surface-resistance ratio, around the element's `C` (STORAGE) — no
independent invention of either conductance.

### Noise-parameter priors (not channel-derived)

The Kalman filter additionally needs **process noise `Q`** (Bacher's Wiener `dω`, which
absorbs unmeasured disturbances and keeps them out of the physical parameters) and
**observation noise `R`** (sensor floor). These are **not** produced by the channel model —
they have no element. They get their own weakly-informative priors: `R` tight around the
known sensor noise floor (~0.1 °C); `Q` weakly-informative, broad. For our collinear data
these trade off against the physical parameters and must be estimated, not fixed.

### The prior-vs-data diagnostic (first-class output)

For every parameter, report **how far the posterior moved from the prior** (in `σ_log`
units), i.e. "did the data actually move this number, or is it sitting at its prior?" For
collinear passive data this is the single most important honesty check — it distinguishes a
fit the data informed from one that merely echoes the priors back. It is promoted here from
the reading note to a first-class app output.

---

## Model assembly

The routing (channels → modules) follows from element kinds, materials, and heavy/light
overrides. The app then:

1. For each element, compute its **channels** (conserved budgets) once.
2. Route each (element, channel) cell to its owning module; **assert exactly-once** per cell.
3. Collect all private states → state-vector dimension.
4. Sum all `flux_room` contributions → RHS for `dT_room/dt`.
5. Append each module's `state_ode` → full ODE system.
6. Collect all `params` → parameter vector; derive log-normal priors by spending budgets.
7. Collect all boundary `signals` → check availability, warn if missing.
8. **Run the pre-fit identifiability report** (§Identifiability) at the prior means.

### Examples

**Current default model** — `RoomMass + DirectLoss + HeavyWall + SolarGain`
State `[T_wall, T_room]`. Heavy-wall CONDUCTION+STORAGE+SOLAR_OPAQUE → HeavyWall; window
CONDUCTION + ACH → DirectLoss; window SOLAR_TRANSMISSION → SolarGain. Params: `H_ve, H_out,
H_in, C_wall, C_room` (+ `Q, R`). Bands: fast (room) + slow (wall) → identifiable in principle.

**Cave / cellar** — `RoomMass + GroundLoss + HeavySlab + AdjacentLoss`
State `[T_slab, T_room]`. No solar channels. Bacher's "constant room" — the honest first fit
target. **Fit-blocked today** by the `T_ground` open question; simulation-only for now.

**Caravan** — `RoomMass + DirectLoss + SolarGain`
State `[T_room]` only. No STORAGE channel offered → no buffered node, single fast band. Model
degrades cleanly to pure-resistive.

**Earthship** — `RoomMass + DirectLoss + SolarGain + HeavySlab(berm) + HeavyWall(south mass)`
State `[T_berm, T_room]` (possibly a south-mass node). Stress-tests both solar channels and
ground-coupled storage. Simulation-only until `T_ground` is solved.

> **Day-one fit reality.** The fit realistically supports
> `RoomMass + DirectLoss [+ SolarGain] [+ one buffered node: HeavyWall or IndoorMass]`.
> The cave and Earthship examples sell the *simulation* modularity; their fits wait on
> `T_ground` and on extra measured states.

---

## Aggregation granularity

Heavy elements can be aggregated into **one** node (fit-friendly) or kept **per-element**
(more faithful, more states). The channel model supports both — it is whether
`HeavyWall.derive_priors` sums its claimed elements into one node or emits one per element.
Decide **per use**: aggregate for the fit (the band rule forbids multiple same-band nodes),
per-element for the toy (expressiveness, no identifiability limit).

---

## Implementation sketch

```python
class Channel(Enum):
    CONDUCTION = auto()
    SOLAR_TRANSMISSION = auto()
    SOLAR_OPAQUE = auto()
    STORAGE = auto()

@dataclass
class Budget:
    UA: float | None = None
    shgcA: float | None = None
    alphaA: float | None = None
    C: float | None = None

class EnvelopeElement:
    # ... geometry, layers, orientation ...
    def channels(self) -> dict[Channel, Budget]:
        """Conserved budgets, computed once, model-agnostic."""

def solar_boundary(orientation, effective_area, weather) -> "FluxSignal":
    """POA irradiance (8 orientations: S, SE, SW, E, W, NE, NW, N) × area → flux.
    Reusable helper, called by SolarGain (→ T_room) and HeavyWall (→ its outer node)."""

@dataclass
class TopologyModule:
    name: str
    params: list[str]
    signals: list[str]          # boundary signals only (star topology)
    private_states: list[str]   # owned, never shared
    owns: list[Channel]

    def derive_priors(self, cells) -> dict[str, tuple[float, float]]:
        """{param: (mu_log, sigma_log)} by spending claimed budgets (log-normal)."""

    def flux_room(self, params, signals, states) -> float: ...
    def state_ode(self, params, signals, states) -> dict[str, float]: ...

class Assembler:
    """Routes channel cells to modules (asserting exactly-once), builds the star ODE,
    collects log-normal priors / params / boundary signals, and produces the pre-fit
    identifiability report (pole bands × input excitation)."""
```

**Topology rendering:** the assembled star graph is drawn with
[schemdraw](https://schemdraw.readthedocs.io/) (Python/matplotlib → static SVG/PNG, served
by FastAPI). Server-side, not a client concern.

---

## Elements

- outer wall (orientation, layers)
- partition (inner wall to adjacent zone)
- indoor mass (furniture / exposed interior slab)
- window (orientation, SHGC)
- floor slab (boundary: ground / adjacent / exposed)
- heat source

(An inner *door* is folded into `partition` — never separately identifiable.)

## Tech stack

- Frontend: Svelte + DaisyUI.
- Backend: FastAPI (Python, `uv`). Local, single-user, single-session. Physics runs
  server-side, including topology rendering.
- Numerics: pure Python (NumPy + `scipy.optimize`). Hand-rolled 2-state LTI Kalman filter
  for the fit. **CTSM-R is a validation oracle only, never a runtime dependency.**

---

## Open questions

1. **Module selection UX**: explicit override for now, defaulting from materials (and, when
   available, from the band-rule criterion). Auto-suggestion ("your building has a heavy
   ground slab — consider `HeavySlab`") deferred.

2. **H_in vs H_int**: keep `H_in` fixed from ISO 6946 inner-surface conductance. Exposing it
   as free adds identifiability cost for a well-constrained quantity. Not worth it now.

3. **T_ground signal**: deferred for the **fit** (hourly Open-Meteo over a year just to
   estimate seasonal ground temperature is impractical; `HeavySlab` needs `T_ground`). For
   the **simulation toy**, `T_ground` is a prescribed scenario input (constant or seasonal
   sinusoid), so `HeavySlab` *can* be exercised forward.

4. **Variable states (occupancy, heating, window state)**: in **simulation** these are
   *prescribed inputs* (`SourceFlux` modules, scenario sliders). In the **fit** they are
   *unmeasured disturbances* that corrupt identifiability — which is why the fit starts with
   a "constant room" (cave/cellar). Same module, two roles.

5. **`IndoorMass` vs `HeavyWall` when both qualify**: both add a buffered node. The band rule
   says keep at most one *per band*. If a room genuinely has both a medium (furniture) and a
   slow (envelope) band with independent excitation, both may be justified — but this is the
   borderline case the identifiability report must flag.

6. **Multi-zone**: out of scope. Single room, single indoor temperature observation.
```
