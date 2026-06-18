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

## Module catalogue

### Always present

| Module | Flux | Parameters | Signals | Extra state |
|---|---|---|---|---|
| `RoomMass` | — | C_room | — | — |

`RoomMass` is the base: it provides C_room and the room temperature node. Every model
includes it. Prior: 20 kJ/(m²·K) × floor area, ±60%.

---

### Memoryless flux modules (no extra state)

| Module | Flux into T_room | Parameters | Signals needed |
|---|---|---|---|
| `FastLoss` | `H_fast × (T_ext − T_room)` | H_fast | T_ext |
| `DirectSolar` | `Σ alpha_i × A_i × G_i` | alpha_i per orientation | G_sol per orientation |
| `GroundSlab` | `H_floor × (T_ground − T_room)` | H_floor | T_ground |
| `AdjacentRoom` | `H_adj × (T_adj − T_room)` | H_adj | T_adj |
| `Heater` | `Q_hvac(t)` | — (signal only) | Q_hvac |
| `Ventilation` | `H_ve × (T_ext − T_room)` | H_ve | T_ext |

`FastLoss` covers window conduction + infiltration. `Ventilation` covers ACH-driven loss.
They could be merged into a single `H_direct` or kept separate depending on available data.

---

### Modules with an extra state

| Module | Extra state | Flux into T_room | ODE for extra state | Parameters | Signals |
|---|---|---|---|---|---|
| `HeavyWall` | T_wall | `H_slow × (T_wall − T_room)` | `C_wall · dT_wall/dt = H_env×(T_sa − T_wall) − H_slow×(T_wall − T_room)` | H_env, H_slow, C_wall, alpha | T_ext, G_sol |
| `HeavySlab` | T_slab | `H_slab_in × (T_slab − T_room)` | `C_slab · dT_slab/dt = H_slab_out×(T_ground − T_slab) − H_slab_in×(T_slab − T_room)` | H_slab_out, H_slab_in, C_slab | T_ground |

`HeavyWall` is exactly the current 2R2C wall path. `HeavySlab` is its ground-floor analogue.
`HeavySlab` is only identifiable if T_ground is measured or modeled (e.g. from climate data at depth).

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
RoomMass + FastLoss + Ventilation + HeavyWall + DirectSolar
```

State: [T_wall, T_room]. Signals: T_ext, G_sol. Parameters: H_fast, H_ve, H_env, H_slow, C_wall, C_room, alpha.

### Example: heavy soil room

```
RoomMass + FastLoss + Ventilation + HeavySlab
```

State: [T_slab, T_room]. Signals: T_ext, T_ground. Parameters: H_fast, H_ve, H_slab_out, H_slab_in, C_slab, C_room.
No solar input needed.

### Example: lightweight modern room

```
RoomMass + FastLoss + Ventilation + DirectSolar + Heater
```

State: [T_room] only. Signals: T_ext, G_sol, Q_hvac. Parameters: H_fast, H_ve, C_room, alpha.
No wall mass — fast dynamics, HVAC-controlled.

---

## Prior estimation per module

Each module reads only the envelope elements relevant to its physics:

| Module | Elements it reads | Prior logic |
|---|---|---|
| `RoomMass` | floor area | 20 kJ/(m²·K) × area |
| `FastLoss` | windows | Σ U×A for windows |
| `Ventilation` | room ACH, volume | 0.34 × ACH × V |
| `HeavyWall` | exterior opaque walls | H_env from Σ U×A; C_wall from heavy layers; alpha from outer material |
| `DirectSolar` | windows (SHGC, area, orientation) | Σ SHGC×A per orientation |
| `GroundSlab` / `HeavySlab` | floor-on-ground elements | H_floor from U×A; C_slab from slab thickness × ρcp |
| `AdjacentRoom` | partition walls to adjacent spaces | H_adj from U×A |

This scoping means **each module's prior is independent**. Adding or removing a module does
not change the priors of the others.

---

## Identifiability constraint

Each extra state and each free parameter requires signal to be identified. With a single
indoor temperature sensor the practical limit is roughly **4–5 free parameters** before
the optimizer becomes underdetermined.

Guidelines:
- `HeavyWall` adds 4 parameters (H_env, H_slow, C_wall, alpha) + 1 state → borderline, needs long time series with temperature swings
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

The `Simulator` assembles modules into a full ODE, the `FitEngine` collects priors and runs
MAP optimization over the union of all `params`, and the frontend shows which modules are
active with their signal requirements and prior estimates.

---

## Open questions

1. **Module selection UX**: auto-detect from available signals + element types, or explicit user choice?
2. **H_slow vs H_env**: in `HeavyWall`, are these the same resistance or two different resistances (inner/outer surface)? Currently H_int is fixed from ISO 6946 geometry — should it remain fixed?
3. **T_ground signal**: use a fixed seasonal model (e.g. Kusuda–Achenbach), a user-provided sensor, or climate API data?
4. **Multi-zone**: two coupled rooms share a partition wall — is that one `AdjacentRoom` module on each side, or a shared node?
