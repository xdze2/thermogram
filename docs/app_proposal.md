# thnodes app Proposal

A small engineering app for

- 1. doing dynamic thermal building simulation: the user describe a house, inputs weather data, inside temperatures is estimated
- 2. identifying the thermal parameters of a room from sensor data, using Bayesian inference

The first layer is a physical description of a room "Elements": Wall (surface, material stack, orientation), Windows, floor, hvac, ...etc

The second layer is RC equivalent model. But in order to resolved the parameter estimation the model have to be minimal.
The RC graphs is build from "Modules", inspired from [BacherMadsin2011](docs/biblio/Journal_article_-_2011_-_Identifying_suitable_models_for_the_heat_dynamics_of_buildings.pdf)

We will focus on a single room model, aka the model predict Ti.

---

## Motivation

The current 2R2C model with sol-air input works well for solar-driven, lightweight rooms.
But different buildings have different dominant dynamics:

- A **cave / cellar** is driven by ground coupling and stored mass, not solar input.
- A **caravan** is all-light: fast dynamics, no wall thermal mass to speak of.
- A **passive house** has very low conduction loss and large controlled solar gain.
- An **Earthship** is dominated by an enormous ground-coupled thermal-mass berm behind a
  large south glazing.

Trying to fit a single fixed 2R2C topology to all these cases produces prior–fit divergence:
the optimizer compensates by pulling parameters to physically implausible values.

The fix is to make the model **composable**: assemble it from flux modules that match the
actual physics of the building, with priors derived from the physical element description.

### Two uses, one engine

Crucially, the modular engine serves **two purposes that share all their assembly code**:

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

①+② are the **simulation toy** (cf. `inertie_nocturne/proposal.md` — a Bret-Victor physics
toy, season-long forward simulation). ③ is the **fit** (phase 2, cf.
`reading_note_bacher_madsen_2011.md`). They share the ODE assembly entirely; the simulation
half is nearly free given the existing `forward_sim` in `state_space.py`, and it de-risks the
engine before any fit is trusted on it.

**Relation to Bacher & Madsen (2011):** we keep their grey-box engine (Kalman
prediction-error likelihood) and white-residual diagnostics, but deliberately **drop their
automatic model selection** — our passive, collinear, occupancy-corrupted data cannot support
it. Instead the topology is **assembled from the physical description**: the user describes the
building element by element, and the modules + their priors follow. This is the right move for
our data regime, not a shortcut.

---

## Core idea: energy balance as a sum of flux modules

The room air energy balance is:

```
C_room · dT_room/dt = Σ Q_i(t)
```

Each module is one term in that sum. A module knows:

- what **parameters** it contributes (free variables for the optimizer / things to sample)
- what **signals** it requires (measured inputs / scenario drivers: T_ext, G_sol, T_ground, …)
- **extra state** (internal temperature node with its own ODE)
- how to **derive its prior** (mu, sigma) from the physical element description

Modules that need an extra state (e.g. a heavy wall with its own temperature) extend the state
vector. All other modules are memoryless fluxes directly into C_room.

---

## Ownership: the (element, channel) model

The naïve idea "each module pulls the elements it wants" breaks down on shared elements. Two
distinct situations look superficially the same but are physically opposite:

1. **Competing models of the same path** — a heavy-wall R-C-R chain _and_ a lumped envelope
   resistance both claiming a south wall's **conduction**. This is genuine **double-counting**:
   the wall's U·A enters the energy balance twice. Illegal.
2. **Distinct additive paths through one element** — a south window contributes **both**
   conduction `U·A·(T_ext − T_room)` **and** solar transmission `SHGC·A·G`. These are different
   physical channels and both _should_ fire. Legitimate, not double-counting.

The resolution is to make the unit of ownership not the element but the **(element, channel)
pair**.

### Channels

Each element exposes a set of **channels**, each a conserved physical budget computed **once**
from ISO 6946 / material layers:

| Channel              | Budget                           | Offered by                         |
| -------------------- | -------------------------------- | ---------------------------------- |
| `CONDUCTION`         | `U·A`                            | opaque walls, windows, roof, floor |
| `SOLAR_TRANSMISSION` | `SHGC·A`                         | glazing                            |
| `SOLAR_OPAQUE`       | `α·A` (sol-air on outer surface) | opaque exterior elements           |
| `STORAGE`            | `C_heavy` (heavy layers only)    | walls/roof/floor with ρ>500 layers |

Keeping `SOLAR_TRANSMISSION` (glazing) separate from `SOLAR_OPAQUE` (sol-air absorptance on
opaque surfaces) honours the rule **one channel = one physical mechanism**, and keeps α out of
the conduction budget.

### The ownership rule

> **Per (element, channel): exactly one module may claim it.**
> **Across channels: an element may be claimed by many modules.**

This single rule covers every case:

| case                            | channels                            | resolution                               |
| ------------------------------- | ----------------------------------- | ---------------------------------------- |
| south window                    | `CONDUCTION` + `SOLAR_TRANSMISSION` | different channels → both fire, correct  |
| heavy vs light wall             | same `CONDUCTION` channel           | one owner → a routing choice             |
| ventilation + window conduction | same `CONDUCTION` (to T_ext)        | merged in one module by design           |
| Earthship berm wall             | `CONDUCTION`(ground) + `STORAGE`    | both owned by the heavy-slab/wall module |

Modules **spend** budgets; they never re-invent them. `HeavyWall.derive_priors` does not
independently invent `H_out, H_in` — it _splits the element's single `U·A`_ (by inner/outer
surface-resistance ratio) around the element's `C_heavy`. This keeps the per-module prior logic
honest (energy and capacity are conserved) and far less bespoke.

The assembler asserts the exactly-once invariant on each channel cell. **Double-counting becomes
a hard error at assembly time, not a silent bug in the fit.**

### Heavy/light routing — inferred default + override

A wall's `CONDUCTION` channel routes to one of two modules, and _that routing is the topology
choice_ (Bacher's "give this wall its own `Te` state, or not"):

- **`DirectLoss`** — lumped memoryless `H`; the wall's `STORAGE` channel (if any) is ignored.
  "Light wall."
- **`HeavyWall`** — claims **both** the wall's `CONDUCTION` _and_ `STORAGE` channels; re-splits
  the U·A into `H_out`/`H_in` around `C_heavy`; adds a `Te` state. "Heavy wall."

The default route is **inferred** from the element's materials (`is_heavy`, ρ>500, already in
`materials_db.py`), with an **optional per-element override** to flip it. Common cases need no
user decision; the override gives full control when wanted.

---

## Four canonical flux forms

All physical terms in the energy balance reduce to one of four mathematical forms:

| Form                                    | Class                | Flux into T_room           | Parameters                 | Reads channels                       | Extra state |
| --------------------------------------- | -------------------- | -------------------------- | -------------------------- | ------------------------------------ | ----------- |
| conductance to a reference temperature  | `Conductance`        | `H × (T_ref − T_room)`     | H                          | CONDUCTION                           | —           |
| irradiance-driven source                | `SolarGain`          | `alpha × A × G`            | alpha·A                    | SOLAR_TRANSMISSION                   | —           |
| conductance through a thermal mass node | `DelayedConductance` | `H_in × (T_node − T_room)` | H_out, H_in, C_node, alpha | CONDUCTION + STORAGE (+SOLAR_OPAQUE) | T_node      |
| prescribed heat input                   | `SourceFlux`         | `Q(t)`                     | —                          | — (raw signal)                       | —           |

The discriminator is: **does it have memory?**

- Memoryless → `Conductance`, `SolarGain`, or `SourceFlux`
- With thermal mass → `DelayedConductance`

`SolarGain` is kept separate from `SourceFlux` because its prior is structured (SHGC × A per
orientation), whereas `SourceFlux` is a raw measured/prescribed signal with no prior on
magnitude.

---

## Module catalogue

### Always present

| Module     | Class | Reads                   | Prior logic               |
| ---------- | ----- | ----------------------- | ------------------------- |
| `RoomMass` | —     | floor area (no channel) | 20 kJ/(m²·K) × area, ±60% |

`RoomMass` is the base node. Every model includes it.

### Memoryless modules

| Module          | Class         | T_ref / signal | Channels it owns                          | Prior logic                          |
| --------------- | ------------- | -------------- | ----------------------------------------- | ------------------------------------ |
| `DirectLoss`    | `Conductance` | T_ext          | CONDUCTION of light walls + windows + ACH | Σ U×A + 0.34×ACH×V                   |
| `GroundLoss`    | `Conductance` | T_ground       | CONDUCTION of light ground-contact floor  | Σ U×A                                |
| `AdjacentLoss`  | `Conductance` | T_adj          | CONDUCTION of partitions                  | Σ U×A                                |
| `SolarGain`     | `SolarGain`   | G_sol          | SOLAR_TRANSMISSION of windows             | Σ SHGC×A per orientation             |
| `InternalGains` | `SourceFlux`  | Q_int          | —                                         | user-supplied constant or schedule   |
| `HVAC`          | `SourceFlux`  | Q_hvac         | —                                         | measured/prescribed signal, no prior |

`DirectLoss` merges window conduction and ACH ventilation: both are `H × (T_ext − T_room)` on
the same conduction-to-T_ext channel, so splitting them brings no modelling benefit.

### Modules with an extra state

| Module      | Class                | Extra state | Flux into T_room           | Node ODE                                                                | Channels owned                                              | Signals      |
| ----------- | -------------------- | ----------- | -------------------------- | ----------------------------------------------------------------------- | ----------------------------------------------------------- | ------------ |
| `HeavyWall` | `DelayedConductance` | T_wall      | `H_in × (T_wall − T_room)` | `C_wall · dṪ_wall = H_out×(T_sa − T_wall) − H_in×(T_wall − T_room)`     | CONDUCTION + STORAGE + SOLAR_OPAQUE of heavy exterior walls | T_ext, G_sol |
| `HeavySlab` | `DelayedConductance` | T_slab      | `H_in × (T_slab − T_room)` | `C_slab · dṪ_slab = H_out×(T_ground − T_slab) − H_in×(T_slab − T_room)` | CONDUCTION + STORAGE of heavy ground-contact elements       | T_ground     |

`HeavyWall` and `HeavySlab` are the same `DelayedConductance` form — they differ only in their
reference signal (T_ext + sol-air vs T_ground) and which elements feed their prior. `HeavySlab`
is only identifiable if T_ground is measured or modeled (e.g. Kusuda–Achenbach). For the
**simulation toy** T_ground can be a prescribed scenario signal; for the **fit** it remains
deferred (see open questions).

---

## Model assembly

The routing (channels → modules) follows from element kinds, materials, and the heavy/light
overrides. The app then:

1. For each element, compute its **channels** (conserved budgets) once.
2. Route each (element, channel) cell to its owning module; **assert exactly-once** on each cell.
3. Collect all `extra_states` → state vector dimension.
4. Sum all `flux_room` contributions → RHS for `dT_room/dt`.
5. Append `state_ode` for each extra state → full ODE system.
6. Collect all `params` → parameter vector.
7. Collect all `signals` → check availability, warn if missing.

### Example: current default model

```
RoomMass + DirectLoss + HeavyWall + SolarGain
```

State: [T_wall, T_room]. Channels: heavy-wall CONDUCTION+STORAGE+SOLAR_OPAQUE → HeavyWall;
window CONDUCTION + ACH → DirectLoss; window SOLAR_TRANSMISSION → SolarGain.
Parameters: H_ve, H_out, H_in, C_wall, alpha, C_room.

### Example: cave / cellar

```
RoomMass + GroundLoss + HeavySlab + AdjacentLoss
```

State: [T_slab, T_room]. No solar channels. Bacher's "constant room" — the honest first fit
target.

### Example: caravan

```
RoomMass + DirectLoss + SolarGain
```

State: [T_room] only. No `STORAGE` channel offered by any element → no heavy node. Fast
dynamics. The model degrades cleanly to pure-resistive.

### Example: Earthship

```
RoomMass + DirectLoss + SolarGain + HeavySlab(berm) + HeavyWall(south mass)
```

State: [T_berm, T_room] (and possibly a south-mass node). Huge `STORAGE` budget from the
rammed-earth berm; large `SOLAR_TRANSMISSION` from the south glazing; `GroundLoss`/`HeavySlab`
for the bermed rear. Stress-tests both solar channels and ground-coupled storage at once.

---

## Identifiability constraint (fit only)

This section applies to **③ the fit** — the **simulation toy (①②) has no identifiability
limit**, because forward integration needs no inversion. The toy can stack as many modules and
states as the physics warrants.

For the fit, each extra state and free parameter requires signal to be identified. With a single
indoor temperature sensor the practical limit is roughly **4–5 free parameters**.

- `HeavyWall` adds 4 parameters + 1 state → borderline, needs long time series with swings.
- `HeavyWall` + `HeavySlab` is 7 parameters + 2 states → only viable with extra measured states.
- Simpler models (1–2 modules beyond `RoomMass`) are more robustly identifiable.

The UI should surface a warning when the selected modules exceed the expected identifiability of
the available data — and should make clear this warning is about _fitting_, not _simulating_.

---

## Aggregation granularity

Heavy elements can be aggregated into **one** node (fit-friendly, current 2R2C behaviour) or
kept **per-element** (more faithful, more states). The channel model supports both — it is just
whether `HeavyWall.derive_priors` sums its claimed elements into one node or emits one per
element. Decide **per use**: aggregate for the fit (identifiability), per-element for the toy
(expressiveness).

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
    # ... geometry, layers ...
    def channels(self) -> dict[Channel, Budget]:
        """Conserved budgets, computed once, model-agnostic."""
        ...

@dataclass
class TopologyModule:
    name: str
    params: list[str]
    signals: list[str]
    extra_states: list[str]
    owns: list[Channel]             # which channels this module claims

    def derive_priors(self, cells: list[tuple[Element, Channel, Budget]]
                      ) -> dict[str, tuple[float, float]]:
        """Return {param_name: (mu, sigma)} by spending the claimed budgets."""
        ...

    def flux_room(self, params, signals, states) -> float: ...
    def state_ode(self, params, signals, states) -> dict[str, float]: ...
```

The four concrete subclasses (`Conductance`, `SolarGain`, `DelayedConductance`, `SourceFlux`)
implement the flux equations. Named modules (`DirectLoss`, `HeavyWall`, …) add prior logic on
top. The `Assembler` routes channel cells to modules (asserting exactly-once), builds the ODE,
and collects priors/params/signals. The same assembled system feeds the forward simulator and
the fit engine.

**Topology rendering:** the assembled module graph can be drawn with
[schemdraw](https://schemdraw.readthedocs.io/) (Python/matplotlib → static SVG/PNG, served by
FastAPI). This fits the server-side-physics decision; it is not a client-side concern.

---

## Elements

- outer wall
- inner wall
- inner mass
- inner door (?)
- window
- floor slab
- heating source

## TopologyModules

| form                       | flux into `T_room`                                  | extra state                  | params                         | channels owned                                                           |
| -------------------------- | --------------------------------------------------- | ---------------------------- | ------------------------------ | ------------------------------------------------------------------------ |
| `RoomMass` (base node)     | `C_room·dṪ_room = ΣQ`                               | **`T_room`**                 | `C_room`                       | none — it _is_ the balance                                               |
| `Conductance`              | `H·(T_src − T_room)`                                | —                            | `H`                            | `CONDUCTION@{T_ext\|T_ground\|T_adj}`                                    |
| `SolarGain` / `SourceFlux` | `α·Q_src` into a **target node** (default `T_room`) | —                            | `α` (SHGC, or HVAC effic.)     | a `SOLAR` or `SOURCE` channel                                            |
| `HeavyWall` (§3.4)         | `H_in·(T_n − T_room)`                               | `T_1…T_n` (n from thickness) | derived from layers            | `CONDUCTION@src` **+** `STORAGE` (+ a `SOLAR` for sol-air on outer node) |
| `IndoorMass` (§3.5)        | `(T_m − T_room)/R_m`                                | **`T_m`**                    | `C_m, R_m` (+ `Φ_h` if heater) | a `SOURCE` channel when the heat source is on                            |

## Tech stack

- web app front using svelte, DaisyUI for css styles
- fastapi api backend (python, uv). Local backend, single user, single session.

---

## Open questions

1. **Module selection UX**: explicit override for now, defaulting from materials. Auto-suggestion
   ("your building has a heavy ground slab — consider `HeavySlab`") deferred.

2. **H_in vs H_int**: keep H_in fixed from ISO 6946 inner-surface conductance, as in the current
   model. Exposing it as a free parameter adds identifiability cost for a well-constrained
   quantity. Not worth it now.

3. **T_ground signal**: deferred for the **fit** (hourly Open-Meteo over a year is impractical
   just to estimate seasonal ground temperature; `HeavySlab` needs T*ground). For the
   **simulation toy**, T_ground is a prescribed scenario input (constant or a seasonal sinusoid),
   so `HeavySlab` \_can* be exercised forward.

4. **Variable states (occupancy, heating, window state)**: in **simulation** these are
   _prescribed inputs_ (`SourceFlux` modules, scenario sliders — the `inertie_nocturne`
   philosophy). In the **fit** they are _unmeasured disturbances_ that corrupt identifiability —
   which is exactly why the fit starts with a "constant room" (cave/cellar). Same module, two
   roles.

5. **Multi-zone**: out of scope. Single room, single indoor temperature observation.
