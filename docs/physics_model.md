# Modular RC — physics model

**The single source of truth** for the modular RC engine's physics: the elements, the channels
they expose, and the module forms that consume those channels into an ODE system. `test_cases.md`
exercises this model on concrete buildings; `modular_rc_proposal.md` gives the design rationale
("why"); `todo_modular_rc.md` is the build roadmap.

Contents: **1.** elements · **2.** channels · **3.** module forms · **4.** assembly ·
**5.** RC↔thermal analogy & schematics.

---

## 1. Elements — generic description

An element is described independently of any module choice:

| field | meaning |
|---|---|
| `kind` | wall / window / roof / floor / door |
| `boundary` | `exterior` / `ground` / `adjacent` / `interior-of-zone` → sets the CONDUCTION source |
| `area`, `orientation`, `tilt` | geometry |
| `layers` (inside→outside) | → `U·A`, `C_heavy`, and `HeavyWall`'s `(k, ρcp, thickness)` prior |
| `shgc` | glazing → `SHGC·A` |
| `α` | exterior opaque → sol-air absorptance; or interior surface lit through glazing |

`boundary` replaces the old `is_ground_contact` boolean and makes "adjacent zone" first-class. What
channels an element offers follows mechanically from `(kind, boundary, layers, shgc, α)`.

---

## 2. Channels — `(mechanism, source)`

### Glossary — keep these distinct

| term | what it is | plane |
|---|---|---|
| **Element** | declarative geometry + materials of one surface (§1). Offers budgets; owns no physics. | input |
| **Mechanism** | a *kind* of heat path: `CONDUCTION` / `SOLAR` / `STORAGE`. | — |
| **Source** | the **other end of a branch**: a boundary temp (`T_ext`/`T_ground`/`T_adj`), a solar driver (`G_sol…`), or `—` for storage (a capacitance has no other end). A source that carries a measured timeseries is a **signal** — but not every source is a signal (storage isn't). | — |
| **Channel** | `(Mechanism, Source)`: a **budget slot** an element offers, e.g. "this wall has `U·A` of `CONDUCTION@T_ext`". | **accounting** |
| **Module** (§3) | one RC sub-part: it **claims** channels (accounting) and **emits** RC branches (physics). *Module + source = one branch* in the assembled circuit. | both |

A **channel** is therefore a **conserved budget** an element offers, computed once from geometry +
ISO 6946 + layers, model-agnostic. The key is a **`(mechanism, source)` tuple** — the *source* is
part of the identity, since conduction to outside, ground, and an adjacent zone are physically
distinct paths.

**Two planes, never conflate them.** A channel lives on the *accounting* plane: it is the unit at
which ownership is enforced, so a budget can't be silently spent twice. It is **not yet a branch**.
The RC branch (resistor to a source, a node, a flux source) is emitted later, on the *physics*
plane, by the owning module's `dynamics()`. "A module claims an `(element, channel)`" is a statement
about accounting; "a module connects an element to a source" is the same module on the physics plane.

| mechanism | source | budget | offered by |
|---|---|---|---|
| `CONDUCTION` | `T_ext` | `U·A` | exterior walls, windows, roof |
| `CONDUCTION` | `T_ground` | `U·A` | ground-contact floors, buried walls |
| `CONDUCTION` | `T_adj` | `U·A` | partitions, ceilings/floors to other zones |
| `CONDUCTION` | `T_ext` (air exchange) | `0.34·ACH·V` | the room (ventilation) |
| `SOLAR` | `G_sol` transmitted | `SHGC·A` | glazing → a target node |
| `SOLAR` | `G_sol` sol-air | `α·A` | opaque exterior surfaces |
| `SOLAR` | `G_sol` interior-absorbed | `α·A` behind glazing | interior mass lit through glazing — `SolarGain` with `target`=a mass node, not a new channel (§3.3) |
| `STORAGE` | — | `C_heavy` (ρ>500 layers) | walls/roof/floor with heavy layers |
| `SOURCE` | prescribed `Q(t)` | — | internal gains, HVAC (raw signal, no budget) |

Source-in-key dissolves near-duplicate modules: one `Conductance` form parameterized by source
covers `T_ext`/`T_ground`/`T_adj`. `STORAGE` is capacity, not flux — always claimed *together with*
a `CONDUCTION` channel by the module that gives the mass its node(s).

**Ownership rule:** per `(element, channel)` exactly one module; across channels an element may be
claimed by several. The assembler asserts exactly-once → **double-counting is a hard error**, not a
silent fit bug.

---

## 3. Module forms

A module is **one RC topology sub-part** — it connects an element to a source. It works on two
planes (§2): on the **accounting** plane it *claims* the `(element, channel)` budget slots it owns;
on the **physics** plane it *emits* the RC branch — declaring **params**, required **signals**
(those of its sources that carry a timeseries), any **extra states** (temperature nodes with their
own ODE), the flux into `T_room`, and how to **derive its prior** by spending the claimed budgets.
Every flux in `C·dT/dt = ΣQ` is one such module.

There are **four flux forms**. Named modules are configurations of these (the source fixes the
name).

| form | flux into `T_room` | extra state | params | channels owned |
|---|---|---|---|---|
| `RoomMass` (base node) | `C_room·dṪ_room = ΣQ` | **`T_room`** | `C_room` | none — it *is* the balance |
| `Conductance` | `H·(T_src − T_room)` | — | `H` | `CONDUCTION@{T_ext\|T_ground\|T_adj}` |
| `SolarGain` / `SourceFlux` | `α·Q_src` into a **target node** (default `T_room`) | — | `α` (SHGC, or HVAC effic.) | a `SOLAR` or `SOURCE` channel |
| `HeavyWall` (§3.4) | `H_in·(T_n − T_room)` | `T_1…T_n` (n from thickness) | derived from layers | `CONDUCTION@src` **+** `STORAGE` (+ a `SOLAR` for sol-air on outer node) |
| `IndoorMass` (§3.5) | `(T_m − T_room)/R_m` | **`T_m`** | `C_m, R_m` (+ `Φ_h` if heater) | a `SOURCE` channel when the heat source is on |

Named configs of `Conductance` by source: `DirectLoss`=`@T_ext` (merges window conduction + ACH);
`GroundLoss`=`@T_ground`; `AdjacentLoss`=`@T_adj`. Of `HeavyWall` by source: `HeavyWall`=`@T_ext`,
`HeavySlab`=`@T_ground`, `HeavyPartition`=`@T_adj`. `HeavyWall` and `IndoorMass` share an internal
RC-chain helper but appear as distinct named modules (see the catalogue note in §3.3).

### 3.1 `RoomMass` — the base node

![RoomMass](diagrams/module_room_mass.png)

The room air balance is itself a module: it owns the `T_room` state and `C_room`; every other
module writes its flux into this node. Not special-cased — same shape as any node-owning module.

### 3.2 `Conductance` — `H·(T_src − T_room)`

![Conductance](diagrams/module_conductance.png)

A resistor `R = 1/H` from a reference temperature to the room. `DirectLoss` / `GroundLoss` /
`AdjacentLoss` are this one form with `T_src` = `T_ext` / `T_ground` / `T_adj`. `DirectLoss` merges
window conduction and ventilation (both `H·(T_ext − T_room)` on the same channel).

### 3.3 `SolarGain` — `α·Q_src` into a **target node**

![SolarGain](diagrams/module_solar_gain.png)

A prescribed flux (current source) injected into a **target node**. Shared by
**solar-through-glazing** (α = SHGC, source `G_sol` per orientation) and **direct heating**
(α = efficiency/COP, source `Q_hvac`) — same math, different prior.

**The target node is a parameter, default `T_room`.** This is the key distinction between *direct*
and *indirect* gain — not the source, but **which node the flux lands on**:

```
direct gain:    Q ─────────────────────────▶ [T_room]      heats the air now
indirect gain:  Q ──▶ [T_m] ──H──▶ [T_room]                heats a mass, which then warms the air
```

For indirect gain the target is the **existing mass node** of the element the source sits on (no new
node needed — the element already offers `STORAGE`):

| source × target | direct (→ `T_room`) | indirect (→ a mass node) |
|---|---|---|
| solar through glazing | light room: gain warms the air | **Trombe wall** — sun lands on the heavy wall behind the glass → that wall's `HeavyWall` node |
| heating | air heater, blown air | **heavy heater** — masonry stove, underfloor slab → the `IndoorMass` node with its source on (§3.5) |

So the earlier "interior-absorbed solar" idea is **not a new channel** — it is just `SolarGain` with
`target` = a mass node.

> **Catalogue, not configuration space.** The two mass modules below (`HeavyWall`, `IndoorMass`)
> share an internal RC-chain helper (the 1-D heat-equation discretization + layer slicing + the
> back-reaction term, written once), but the **catalogue exposes named modules, not a generic
> `RChain(N, H_out, …)`**. `N` and the boundary conductances are implementation details of each
> named module, not user-facing knobs. This keeps the catalogue enumerable and readable while the
> tricky math lives in one place.

### 3.4 `HeavyWall` — a heavy envelope element's thermal mass

![RChain](diagrams/module_rchain.png)

A heavy wall/roof/floor between an outer source (`T_ext` sol-air / `T_ground` / `T_adj`) and the
room. Internally an RC chain — the 1-D heat equation discretized into a few cells:

```
outer src ──H_out──[C_1]──H_1── … ──[C_n]──H_in── T_room
                     │                  │
              (optional sol-air)   (back-reaction into RoomMass)
```

The inner node feeds the room `H_in·(T_n − T_room)`, **and the room balance receives the
equal-and-opposite `+H_in·(T_n − T_room)`** — a mass node is never write-only, it pushes back on
`RoomMass`.

**Params derived from the ordered layer stack** — `k_eq`, `(ρcp)_eq`, thickness — sliced into cells
(`R_i`, `C_i`). The **number of cells `n` is auto-picked from thickness** (thin wall → 1, 40 cm
brick → several) and is **not a free fit parameter**; the fit sees a small fixed param set
regardless. An **advanced override** can set `n` explicitly. Slicing *in layer order* is what lets
the same materials produce opposite dynamics for external vs internal insulation (see the ITE/ITI
case in `test_cases.md`).

Configs by source: `HeavyWall`=`@T_ext` (sol-air), `HeavySlab`=`@T_ground`,
`HeavyPartition`=`@T_adj` — same module, different reference signal.

### 3.5 `IndoorMass` — a one-sided interior mass, **heat source optional**

![furniture](diagrams/module_rchain_furniture.png)

An interior mass coupled to the room on one side only (adiabatic outer face). One module covers two
roles via an **optional heat source on the node**:

| source | role | this is |
|---|---|---|
| **off** (`Φ=0`) | passive interior thermal mass — furniture, finishes, partitions | the weak interior-inertia term |
| **on** (`Φ_h`) | heater with thermal mass — masonry stove, storage radiator, underfloor slab | **Bacher & Madsen's `Th` state** |

```
(Φ_h optional) ──▶ [C_m, T_m] ──1/R_m── T_room
```

Node ODE and room back-reaction:
```
C_m · dṪ_m = Φ_h − (T_m − T_room)/R_m        (Φ_h = 0 for passive furniture)
room balance receives  +(T_m − T_room)/R_m
```

This **resolves the earlier overlap** — furniture and heater were two ways to spell the same
topology; now they are one module, the source flag the only difference. With the source on, the
params `C_m`(=`Ch`), `R_m`(=`Rih`) and signal `Φ_h` are Bacher's `Th` exactly (the `h` in his
`Ti → TiTh → TiTeTh → …` path; `Φ_h` was a PRBS in his experiment — see the reading note). The
heater earns its own state and so costs identifiability: viable in the fit only with a well-excited
heat-input signal; always fine for the forward-simulation toy.

---

## 4. Assembly

1. For each element, compute its **channels** (conserved budgets) once.
2. Route each `(element, channel)` cell to its owning module; **assert exactly-once** on each cell.
3. Collect all `extra_states` → state-vector dimension.
4. Sum all `flux_room` contributions → RHS for `dT_room/dt`.
5. Append each extra state's `state_ode` → full ODE system.
6. Collect all `params` → parameter vector; collect all `signals` → check availability, warn if
   missing.

The same assembled system feeds both the forward simulator (①②) and the fit engine (③).

**Granularity** is a per-use choice: aggregate heavy elements into one `HeavyWall` node
(single-cell, fit-friendly, recovers current 2R2C) or keep them per-element (more faithful, more
states, for the simulation toy). It is just whether one `HeavyWall` sums claimed elements into one
node or the assembler emits one per element.

---

## 5. RC ↔ thermal analogy & schematics

| electrical | thermal | unit |
|---|---|---|
| voltage `V` | temperature `T` | K |
| current `I` | heat flux `Q` | W |
| resistor `R` | thermal resistance `R = 1/H` | K/W |
| capacitor `C` | thermal mass `C` | J/K |
| ground (datum) | 0 K reference | — |
| voltage source | prescribed temperature (`T_ext`, `T_ground`, `T_adj`) | — |
| current source | prescribed heat flux (solar, HVAC) | — |

**Schematics (decision):** topology diagrams are rendered **server-side** with
[schemdraw](https://schemdraw.readthedocs.io/) → **SVG** (not PNG), because the assembled module
graph lives server-side and SVG is crisp at any zoom, themeable via CSS (matches the DaisyUI theme
switcher), and inlinable for later live-temperature animation — all without a JS topology library.
The generic per-form glyphs above are produced by [`draw_modules.py`](draw_modules.py)
(`uv run --with schemdraw --with matplotlib docs/draw_modules.py`); the engine-driven, per-study
renderer is **Stage 4** (`thermal/draw.py`).

---

## Validation status (from the Stage 0 expressiveness pass)

Exercised against six buildings in `test_cases.md`:

- **Exactly-once invariant:** holds in all six cases.
- **`(mechanism, source)` key:** validated — ground/adjacent become first-class, the three loss
  modules collapse to one `Conductance`, and `HeavyPartition` fell out free.
- **Mass modules:** validated — `HeavyWall` (multi-cell, auto `n` from thickness; ITE/ITI needs the
  multi-cell slicing) and `IndoorMass` (one-sided, source optional) cover the wall, furniture, and
  heater cases off one shared internal RC-chain helper.
- **`RoomMass` as a module:** validated.

### Resolved

- **Direct vs indirect gain (Trombe wall / heavy heater).** Not a new channel: `SolarGain` /
  `SourceFlux` take a **`target` node** (default `T_room`). Direct gain → `T_room`; indirect gain →
  a mass node (the lit element's `HeavyWall` cell for a Trombe wall; `IndoorMass` with the source on
  for a masonry stove / underfloor slab, §3.5 = Bacher's `Th`). *(Earthship, heavy heater)*
- **Furniture/heater overlap.** Collapsed into one `IndoorMass` module with an optional heat source
  — no two-spellings ambiguity for the assembler. *(see §3.5)*
- **Module catalogue vs configuration space.** The parametrizable chain is demoted to an internal
  helper; the catalogue exposes named modules (`HeavyWall`, `IndoorMass`, …). `n`/boundary
  conductances are implementation details, not user knobs.

### Open holes / decisions (none block; for Stage 2 design)

1. **Heavy/light routing key:** route on the element's actual `C_heavy` magnitude (+ override), not
   the material-ρ `is_heavy` flag — a 1 mm metal skin (ρ=7800) must stay light or it spawns a
   ~0-capacity node. *(Caravan)*
2. **Position of heavy layer vs insulation** governs coupling — lives in `HeavyWall`'s per-cell
   `R_i/C_i` derivation from the *ordered* layer stack, not a new channel. Headlined by the ITE/ITI
   case. Renovation extras — thermal bridges (a `U·A` correction, deferred) and humidity
   (orthogonal, out of scope) — are not modelled.

**Sensor model:** deferred to ③ the fit (Bacher's measurement equation `y = T_room + e`);
passthrough for ①② simulation.
