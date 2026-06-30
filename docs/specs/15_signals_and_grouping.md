# 15 — Signals & Grouping (the authoring model)

**Status: TARGET.** This spec describes the intended authoring model. The current code does
**not** yet satisfy it — it still exposes the generic element×channel routing matrix as the
authoring surface (modules added by hand, elements ticked into them). The
[§Migration from the routing-matrix model](#migration-from-the-routing-matrix-model) section
says exactly what changes. When this lands, modules become a **derived, read-only** view and
this file describes existing behavior.

This spec **supersedes the "make the (element, channel) mapping visible / route elements into
modules by hand" thesis** of the earlier specs. Channels and the (element, channel) ownership
model are **not removed** — they remain the assembler's internal conservation bookkeeping
(see [`40_physics.md`](40_physics.md) I2–I4). What changes is that they stop being the
**authoring vocabulary**. The user never operates a routing matrix.

---

## Why this exists (the v0.3 thesis, applied consistently)

v0.3's whole reason for being (see [`../README.md`](../../README.md) → *Design history*) is
that the generic physical-description → reduced-model mapping is **ill-posed** — v0.1 proved
it has no unique solution. v0.3 escaped by **not** solving it generically: it picks the model
from a small, hand-curated, building-physics-specific catalogue. Parsimony by **menu**, not by
**algorithm**.

The element×channel **routing matrix re-imported that generality.** It is a generic
many-to-many bipartite join (any element offers any channel; any module claims any channel;
the user wires the matrix; a generic exactly-once invariant polices an open graph). That
machinery is sized for a problem v0.3 deliberately does not have. With the actual catalogue,
the routing "choice" is almost entirely **forced** (a window's solar goes to solar gain; a
heavy wall goes to the heavy-wall treatment) — the user was being asked to operate a generic
matrix to make decisions that are, in reality, one binary per wall plus defaults.

So this spec moves the authoring vocabulary to where the real decisions are:

1. **Per-element-type forms.** The user authors *elements* (a wall, a window, a partition),
   each with kind-appropriate fields — including the **boundary it couples to**.
2. **The boundary (Signal) is the grouping key.** Modules are **derived** by grouping
   elements that share a *(treatment, boundary-signal)*. The user does not add modules or
   route elements; modules fall out of the elements.
3. **The only authoring knob is the treatment** — and even that is usually forced. The one
   genuine choice the proposal sanctions (heavy-vs-light routing of a wall) is a control on
   the *element* card, nowhere else.

---

## The missing concept: the Signal (boundary source / input)

Look at what a module *is*, mechanically ([`forms.py`](../../src/thnodes/forms.py)): a flux
into `T_room` driven by **exactly one boundary signal**. `Conductance` has a `T_bnd_signal`;
`SolarGain` has a `G_signal`; `DelayedConductance` has a `T_bnd_signal`. The star-topology
invariant ([`40_physics.md`](40_physics.md) I1) is literally: one terminal is `T_room`, the
other is *a boundary signal*.

> **A module is identified by its boundary signal, not by its channel.** The channel says
> *which conserved budget feeds the prior*; the signal says *which boundary the branch
> connects to* — and therefore *which elements belong to the same module*.

### Notation: `ModuleType[Signal]`

Because a derived module is fully identified by *(its type, its boundary signal)*, we write it
as **`ModuleType[Signal]`** throughout these specs:

- `DirectLoss[T_ext]` — lumped conduction to outside.
- `DirectLoss[T_kitchen]` — a *distinct* module: conduction to the kitchen.
- `SolarGain[G_sol_S]`, `SolarGain[G_sol_W]` — south- and west-glazing solar, two modules.
- `HeavyWall[T_ext]` — the R-C-R wall branch to outside.
- `RoomMass` — written without a bracket; its boundary is `T_room` itself (the room node), so
  there is nothing to disambiguate.

The bracketed signal **is** the grouping key's second half (I8): two elements produce the same
module iff they share both the `ModuleType` (from their treatment) and the `[Signal]` (from
their boundary). The notation makes "why are these two windows one module but those two are
not" legible at a glance.

The old catalogue hid this because every example collapsed to a single `T_ext` and a single
`G_sol`. The moment a room has **two adjacent rooms** or **two glazing orientations**, the
grouping is by **source**, and the old single-`DirectLoss` / single-`SolarGain` routing
cannot express it at all. Concretely:

| Elements                         | Group into                              | Driven by signal |
| -------------------------------- | --------------------------------------- | ---------------- |
| all light conduction to outside  | one `DirectLoss`                        | `T_ext`          |
| partition → kitchen, partition → kitchen | one `DirectLoss`                  | `T_kitchen`      |
| partition → hallway              | a **separate** `DirectLoss`             | `T_hallway`      |
| floor on ground                  | `GroundLoss` (or `DirectLoss`)          | `T_ground`       |
| south windows (solar)            | one `SolarGain`                         | `G_sol_S`        |
| west windows (solar)             | a **separate** `SolarGain`              | `G_sol_W`        |
| heavy south wall                 | `HeavyWall`                             | `T_ext` (+ sol-air) |

This also closes a loop: **the set of signals the modules demand is exactly the set of inputs
the user must supply to simulate.** Signals are simultaneously the *grouping key* and the
*input list*. The right-column "Time range & signals" panel ([`20_layout.md`](20_layout.md))
is **generated from the assembly** — "your model needs `T_ext`, `T_kitchen`, `G_sol_S`:
provide a series for each."

---

## Signal as a first-class object

A **Signal** is a named boundary input the model couples to. It is part of the room document.

```jsonc
// Signal (document resource)
{
  "id":   "s_kitchen",
  "name": "T_kitchen",          // unique within the model; used as the ODE signal name
  "kind": "temperature",        // "temperature" | "irradiance" | "flux"
  "role": "adjacent",           // see signal roles below
  "meta": { "orientation": "S" } // role-specific (e.g. solar orientation/tilt); else {}
}
```

### Signal roles

| `role`       | `kind`        | Produced by                          | Default ODE name |
| ------------ | ------------- | ------------------------------------ | ---------------- |
| `exterior`   | temperature   | any element with boundary = outside  | `T_ext`          |
| `ground`     | temperature   | floor/wall with boundary = ground    | `T_ground`       |
| `adjacent`   | temperature   | partition/floor to a named room      | `T_<roomlabel>`  |
| `solar`      | irradiance    | glazing / opaque solar, per orientation | `G_sol_<orient>` |
| `prescribed` | flux          | HVAC, internal/occupancy gains       | `Q_<label>`      |

- `exterior`, `ground`, and each distinct `solar` orientation are **singletons** the system
  auto-creates as soon as one element needs them.
- `adjacent` signals are **per named neighbour** — two partitions naming `"kitchen"` share one
  `T_kitchen`; a partition naming `"hallway"` gets its own.
- `prescribed` signals are author-created (an HVAC input, an occupancy gain).

### Signals are mostly auto-created, not hand-authored

The user does not normally open a "new Signal" dialog. Setting `Window.orientation = S`
**ensures** a `G_sol_S` signal exists (creating it if absent) and the element references it.
Adding a `Partition` whose neighbour is `"kitchen"` ensures `T_kitchen` exists. The Signal
list is a **byproduct of authoring elements with boundaries**. The user *can* inspect and
manage it (rename, see which still lack data, delete an orphaned one), but creation is
implicit for all roles except `prescribed`.

> **Invariant (signal liveness).** A Signal exists in the document iff at least one element
> references it **or** it is `prescribed`. Editing/deleting the last element that references
> an auto-signal garbage-collects it. The assembler never demands a signal no element drives.

### A Signal is a *declaration of a required input*, not the data itself

A Signal names and types an input the model needs (`T_kitchen`, a temperature); it does **not**
hold the time series. **Binding a Signal to actual data is a separate layer, deferred to a
future version.** Today (and through the first cut of this model) a Signal's data is supplied
ad-hoc per simulation run — a series in the `/simulate` body, or a synthetic scenario.

The deferred **data-source layer** will map each Signal to a real provenance:

- a column of an uploaded CSV / weather file,
- a query against a time-series store (e.g. **InfluxDB**: measurement + tags + field + range),
- a constant or a schedule (the common case for `prescribed` HVAC/occupancy),
- a derived signal (e.g. `G_sol_S` computed from a `GHI` source via the POA transposition in
  `solar.py`, so the *raw* source is GHI + sun position, not per-orientation irradiance).

Design implication for **now**: keep the Signal object's identity (`id`, `name`, `kind`,
`role`, `meta`) **independent of its data binding**, so a future `binding` / `source` field can
be attached without disturbing grouping, the assembly, or the ODE signal names. Grouping
depends only on Signal *identity*; data provenance is orthogonal and must stay that way. This
is why `meta` already carries derivation hints (solar orientation/tilt) — those belong to the
signal's *definition*, whereas "which InfluxDB series fills it" belongs to the future binding
layer.

---

## Elements declare their boundary

Every envelope element carries a **boundary reference** — *which signal its outer terminal
couples to* — chosen with kind-appropriate options. `Floor.boundary` is the prototype to
generalize across element types.

| Element     | Boundary field(s)                                | Signal(s) it pins                          |
| ----------- | ------------------------------------------------ | ------------------------------------------ |
| `OuterWall` | `orientation` (S…N)                              | `T_ext` (conduction) + `G_sol_<orient>` (opaque solar, heavy only) |
| `Window`    | `orientation` (S…N)                              | `T_ext` (conduction) + `G_sol_<orient>` (transmitted solar) |
| `Floor`     | `boundary` ∈ {ground, adjacent:`<room>`, exposed} | `T_ground` / `T_<room>` / `T_ext`          |
| `Partition` | `adjacent` = `<room label>`                      | `T_<room>`                                 |
| `IndoorMass`| — (interior)                                     | — (auto-paired to RoomMass; see I4)        |
| `HeatSource`| `signal` = a `prescribed` flux signal            | `Q_<label>`                                |

The **new field design** vs. today: `Partition` gains an `adjacent` room-label field (it has
none today); `Floor.boundary`'s `adjacent` option gains a room label; walls/windows keep
`orientation` but it now *pins solar + exterior signals* rather than being a passive tag.

---

## Grouping rule (deterministic, hardcoded — not a search)

The assembler derives modules by a **fixed rule**, not by user routing and not by any
optimisation. The rule is a pure function of (element type, element fields, treatment, the
signals the element pins).

```
for each element e:
    treatment = treatment_of(e)             # forced default, or the element's heavy/light knob
    for each (form, signal) e contributes under `treatment`:
        key = (treatment_module_type, signal)
        modules[key].claim(e, channel)      # accumulate the element's budget for that channel
emit one module per distinct key
```

- **One module per distinct `(treatment, signal)`.** Two south windows → one
  `SolarGain[G_sol_S]`. A south and a west window → two `SolarGain` modules. Two partitions to
  the kitchen → one `DirectLoss[T_kitchen]`.
- The module's **prior** is derived by spending the **summed** channel budgets of its claimed
  elements — exactly as today ([`40_physics.md`](40_physics.md) I4), just over an
  auto-grouped element set instead of a hand-routed one.
- The (element, channel) **exactly-once** invariant (I3) still holds and is still checked — it
  is now an *internal consistency assertion on the rule's output*, not a user-facing
  constraint. A correctly-implemented rule never produces a double-count; if it does, that is
  an engine bug surfaced as a `problem`, not user error.

### Treatment menus (the only authoring knob)

| Element             | Treatments                                  | Module(s) produced                                    |
| ------------------- | ------------------------------------------- | ----------------------------------------------------- |
| `OuterWall` (heavy) | **Thermal-mass wall** (default) · Simple loss | `HeavyWall[T_ext]` · `DirectLoss[T_ext]`              |
| `OuterWall` (light) | Simple loss *(forced)*                      | `DirectLoss[T_ext]`                                   |
| `Window`            | Glazing *(forced)*                          | `DirectLoss[T_ext]` (cond) + `SolarGain[G_sol_<o>]`   |
| `Floor`             | by `boundary` *(forced)*                    | `GroundLoss[T_ground]` · `DirectLoss[T_<room>]` · `DirectLoss[T_ext]` |
| `Partition`         | Interior loss *(forced)*                    | `DirectLoss[T_<room>]`                                |
| `IndoorMass`        | Room mass *(forced, auto)*                  | `RoomMass`                                            |
| `HeatSource`        | Prescribed flux *(forced)*                  | `SourceFlux[Q_<label>]`                               |

"Heavy" vs "light" for a wall is decided by whether its layers carry a STORAGE budget
(`is_heavy`), exactly as today; the menu only *offers the override* on a heavy wall (model it
as a simple loss anyway). This is the single binary the proposal sanctions
([`../background/app_proposal.md`](../background/app_proposal.md) §"Heavy/light routing"); it
lives on the **element** card, not on a module.

> **Extensibility is by adding a rule, not by freewiring.** If a future element type admits
> two sensible wirings, you add a treatment-menu entry and its grouping rule — reviewable,
> testable, physically meaningful — rather than re-opening a generic routing matrix. That is
> the v0.3 trade (flexibility → curated rules) applied to the UI.

---

## What the user does, end to end

1. Add an `IndoorMass` (room geometry) → `RoomMass` exists, `C_room` derived.
2. Add elements; each form asks for its boundary (orientation / neighbour / ground…). Signals
   auto-appear as needed.
3. For a **heavy** wall, optionally flip its treatment to "simple loss".
4. The **derived topology** (read-only): one branch per `(treatment, signal)` module, each
   labelled by its boundary signal. The user reads it; they don't wire it.
5. The **inputs panel** lists every signal the model needs; the user supplies a series per
   signal (or picks a scenario), then simulates.

No "add module", no routing checkboxes, no element×channel matrix in the edit loop. The matrix
survives only as the collapsible **diagnostic** ([`20_layout.md`](20_layout.md)) — the *check*
that the rule produced exactly-once, complete ownership — which stays quiet unless a `problem`
fires.

---

## Migration from the routing-matrix model

| Concern        | Was (routing-matrix model)                                   | Now (signal-grouping model)                                  |
| -------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| Modules        | User adds them (`POST /modules`) and routes elements in.     | **Derived** by the grouping rule; no add/route endpoints.    |
| Routing        | `doc.routes[mid] = [element_ids]`; `PUT …/routing`.          | **Gone.** Membership is computed from element boundaries.    |
| Boundary       | Implicit; single `T_ext` / single `G_sol`.                   | Explicit per-element boundary ref → first-class **Signal**.  |
| Authoring knob | Tick element×module cells.                                   | Per-element **treatment** (usually forced).                  |
| Channels       | The *visible* authoring vocabulary.                          | **Internal** conservation bookkeeping + a diagnostic only.   |
| Inputs         | Ad-hoc `signals` dict in `/simulate`; `_T_sol_air` hack.     | Generated from the assembly's required-signal set.           |
| API            | `module_types[].owns` drives a routing UI; module CRUD.      | Registry gains **treatment menus** + **signal roles**; module CRUD retired. See [`30_api.md`](30_api.md). |

The engine invariants in [`40_physics.md`](40_physics.md) (star topology, exactly-once
ownership, four forms, log-normal priors, the band rule) are **unchanged in substance** — I2
and I3 are now phrased as properties the grouping rule *guarantees* rather than constraints the
user must satisfy. See [`40_physics.md`](40_physics.md) I8 (the grouping rule) and the amended
I2/I3 framing.

---

## Open questions (exploration-phase; not yet decided)

- **Solar transposition per orientation/tilt.** `solar.py` already computes POA per
  orientation; tilt is hardcoded vertical. A `G_sol_<orient>` signal should carry its
  orientation (and eventually tilt) in `meta` so the weather→POA step is per-signal. Roofs
  (tilted) are the forcing case.
- **Identifiability across split sources.** Splitting one `DirectLoss[T_ext]` into
  `DirectLoss[T_ext]` + `DirectLoss[T_kitchen]` adds a parameter. The band rule / lens
  ([`40_physics.md`](40_physics.md) I7) must judge whether two boundary signals are distinct
  enough to separate the two conductances — if `T_kitchen` tracks `T_ext`, they collapse. This
  is the identifiability question the signal split makes concrete; the lens already has the
  collinearity machinery for it.
- **Prescribed signals UX.** HVAC and occupancy gains are the only author-created signals;
  how they're entered (constant, schedule, uploaded series) is a right-column concern, not
  settled here.
- **Signal → data-source binding (future version).** Mapping each Signal to a real provenance
  — uploaded file column, **InfluxDB query** (measurement/tags/field/range), constant/schedule,
  or a derived chain (GHI + sun position → POA). This is a distinct layer that must attach a
  `binding` to a Signal *without* touching its identity or the grouping (see §"A Signal is a
  declaration of a required input"). Open: where bindings live (on the Signal, or a separate
  data-source registry shared across models), and how a fit study selects a time range over a
  bound source. Not in the first cut; the Signal shape is being kept binding-agnostic so this
  can land later without a migration.
