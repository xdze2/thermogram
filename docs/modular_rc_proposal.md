# Modular RC Model — Design Proposal

## Motivation

The current 2R2C model with sol-air input works well for solar-driven, lightweight rooms.
But different rooms have different dominant dynamics:

- A room with a **heavy ground slab** is driven by floor inertia, not solar input.
- A **well-insulated modern room** has fast dynamics — no wall thermal mass to speak of.
- A room with **HVAC** has a controlled heat source that dominates the energy balance.

Trying to fit a fixed 2R2C topology to all these cases produces prior–fit divergence: the
optimizer compensates by pulling parameters to physically implausible values.

The fix is to make the model **composable**: the user (or the app) assembles the model from
flux modules that match the actual physics of the room.

---

## Core idea: energy balance as a sum of flux modules

The room air energy balance is:

```
C_room · dT_room/dt = Σ Q_i(t)
```

Each module is one term in that sum. A module knows:
- what **parameters** it contributes (free variables for the optimizer)
- what **signals** it requires (measured inputs: T_ext, G_sol, T_ground, …)
- whether it needs an **extra state** (internal temperature node with its own ODE)
- how to **estimate its prior** (mu, sigma) from the physical element description

Modules that need an extra state (e.g. a heavy wall with its own temperature) extend the
state vector. All other modules are memoryless fluxes directly into C_room.

---

## Four canonical flux forms

All physical terms in the energy balance reduce to one of four mathematical forms:

| Form | Class | Flux into T_room | Parameters | Signals | Extra state |
|---|---|---|---|---|---|
| conductance to a reference temperature | `Conductance` | `H × (T_ref − T_room)` | H | T_ref | — |
| irradiance-driven source | `SolarGain` | `alpha × A × G` | alpha·A | G_sol | — |
| conductance through a thermal mass node | `DelayedConductance` | `H_in × (T_node − T_room)` | H_out, H_in, C_node, alpha | T_ref, G_sol | T_node |
| prescribed heat input | `SourceFlux` | `Q(t)` | — | Q | — |

The discriminator is: **does it have memory?**
- Memoryless → `Conductance`, `SolarGain`, or `SourceFlux`
- With thermal mass → `DelayedConductance`

`SolarGain` is kept separate from `SourceFlux` because its prior is structured (SHGC × A
per orientation), whereas `SourceFlux` is a raw measured signal with no prior on magnitude.

---

## Module catalogue

### Always present

| Module | Class | T_ref / signal | Elements it reads | Prior logic |
|---|---|---|---|---|
| `RoomMass` | — | — | floor area | 20 kJ/(m²·K) × area, ±60% |

`RoomMass` is the base node. Every model includes it.

---

### Memoryless modules

| Module | Class | T_ref / signal | Elements it reads | Prior logic |
|---|---|---|---|---|
| `DirectLoss` | `Conductance` | T_ext | windows + ACH | Σ U×A (windows) + 0.34×ACH×V (vent) |
| `GroundLoss` | `Conductance` | T_ground | floor-on-ground | Σ U×A for ground-contact floor |
| `AdjacentLoss` | `Conductance` | T_adj | partition walls | Σ U×A for partitions |
| `SolarGain` | `SolarGain` | G_sol | windows | Σ SHGC×A per orientation |
| `InternalGains` | `SourceFlux` | Q_int | — | user-supplied constant or schedule |
| `HVAC` | `SourceFlux` | Q_hvac | — | measured signal, no prior |

`DirectLoss` merges window conduction and ACH ventilation: both are `H × (T_ext − T_room)`
with the same signal, so splitting them into two modules brings no modelling benefit.

---

### Modules with an extra state

| Module | Class | Extra state | Flux into T_room | Node ODE | Parameters | Signals |
|---|---|---|---|---|---|---|
| `HeavyWall` | `DelayedConductance` | T_wall | `H_in × (T_wall − T_room)` | `C_wall · dṪ_wall = H_out×(T_sa − T_wall) − H_in×(T_wall − T_room)` | H_out, H_in, C_wall, alpha | T_ext, G_sol |
| `HeavySlab` | `DelayedConductance` | T_slab | `H_in × (T_slab − T_room)` | `C_slab · dṪ_slab = H_out×(T_ground − T_slab) − H_in×(T_slab − T_room)` | H_out, H_in, C_slab | T_ground |

`HeavyWall` and `HeavySlab` are the same `DelayedConductance` form — they differ only in
their reference signal (T_ext+solar vs T_ground) and which envelope elements feed their prior.
`HeavySlab` is only identifiable if T_ground is measured or modeled (e.g. Kusuda–Achenbach).

---

## Model assembly

The user selects which modules are active. The app then:

1. Collects all `extra_states` → determines state vector dimension
2. Sums all `flux_room` contributions → RHS for `dT_room/dt`
3. Appends `state_ode` for each extra state → full ODE system
4. Collects all `params` → parameter vector for the optimizer
5. Collects all `signals` → checks which are available, warns if missing

### Example: current default model

```
RoomMass + DirectLoss + HeavyWall + SolarGain
```

State: [T_wall, T_room]. Signals: T_ext, G_sol. Parameters: H_ve, H_out, H_in, C_wall, alpha, C_room.

### Example: heavy ground-floor room

```
RoomMass + DirectLoss + HeavySlab
```

State: [T_slab, T_room]. Signals: T_ext, T_ground. Parameters: H_ve, H_out, H_in, C_slab, C_room.
No solar input needed.

### Example: lightweight HVAC room

```
RoomMass + DirectLoss + SolarGain + HVAC
```

State: [T_room] only. Signals: T_ext, G_sol, Q_hvac. Parameters: H_ve, alpha·A, C_room.
No wall mass — fast dynamics, HVAC-controlled.

---

## Identifiability constraint

Each extra state and each free parameter requires signal to be identified. With a single
indoor temperature sensor the practical limit is roughly **4–5 free parameters** before
the optimizer becomes underdetermined.

Guidelines:
- `HeavyWall` adds 4 parameters (H_out, H_in, C_wall, alpha) + 1 state → borderline, needs long time series with temperature swings
- Combining `HeavyWall` + `HeavySlab` is 7 parameters + 2 states → only viable with both T_int and one of T_wall or T_slab measured
- Simpler models (1–2 modules beyond `RoomMass`) are more robustly identifiable from short datasets

The UI should surface a warning when the selected module combination exceeds the expected
identifiability of the available data.

---

## Implementation sketch

```python
@dataclass
class FluxModule:
    name: str
    params: list[str]               # names of free parameters
    signals: list[str]              # required signal names
    extra_states: list[str]         # names of extra state variables ([] for memoryless)

    def prior(self, elements: list[EnvelopeElement]) -> dict[str, tuple[float, float]]:
        """Return {param_name: (mu, sigma)} from physical description."""
        ...

    def flux_room(
        self, params: dict[str, float], signals: dict[str, float], states: dict[str, float]
    ) -> float:
        """Heat flux into T_room [W] at one timestep."""
        ...

    def state_ode(
        self, params: dict[str, float], signals: dict[str, float], states: dict[str, float]
    ) -> dict[str, float]:
        """dX/dt for each extra state [unit/s]. Empty dict for memoryless modules."""
        ...
```

The four concrete subclasses (`Conductance`, `SolarGain`, `DelayedConductance`, `SourceFlux`)
implement the flux equations. Named modules (`DirectLoss`, `HeavyWall`, …) are instances or
thin subclasses that add prior estimation logic on top.

The `Simulator` assembles modules into a full ODE, the `FitEngine` collects priors and runs
MAP optimization over the union of all `params`, and the frontend shows which modules are
active with their signal requirements and prior estimates.

---

## Open questions

1. **Module selection UX**: explicit user choice for now. Auto-detect from available signals and element types (e.g. "your room has a heavy ground slab — consider adding `HeavySlab`") is deferred to a later iteration.

2. **H_in vs H_int**: keep H_in fixed from ISO 6946 inner-surface conductance, same as the current model. Exposing it as a free parameter adds an identifiability cost for a physically well-constrained quantity. Not worth the complexity now.

3. **T_ground signal**: deferred. The current weather source is hourly Open-Meteo data, which is impractical to pull for a full year just to estimate a seasonal ground temperature. `HeavySlab` requires T_ground and will not be implemented until a lightweight ground temperature model or data source is identified.

4. **Multi-zone**: out of scope. The app fits a single room with a single indoor temperature observation. Coupling two rooms via a shared partition adds model and data complexity that is not warranted at this stage.
