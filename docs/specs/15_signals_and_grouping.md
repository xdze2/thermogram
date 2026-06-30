# 15 — Signals & Grouping (the authoring model)

**Status: BUILT.** This describes existing behavior. `src/thnodes/grouping.py` implements
the deterministic `(treatment, boundary-signal) → Module[Signal]` rule; every assembly
endpoint (`GET /assembly`, `/simulate`, `/topology.svg`, `/identifiability`) is driven by it.
The routing-matrix model (user-added modules, `POST /modules`, `PUT …/routing`) is fully
retired — those endpoints return 404. See `docs/background/` for design history.

---

## The Signal (boundary input)

A **Signal** is a named boundary input the model couples to. It is a first-class document
resource.

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

| `role`       | `kind`        | Created by                              | Default ODE name    |
| ------------ | ------------- | --------------------------------------- | ------------------- |
| `exterior`   | temperature   | any element with boundary = outside     | `T_ext`             |
| `ground`     | temperature   | floor/wall with boundary = ground       | `T_ground`          |
| `adjacent`   | temperature   | partition/floor to a named neighbour    | `T_<roomlabel>`     |
| `solar`      | irradiance    | glazing / opaque solar, per orientation | `G_sol_<orient>`    |
| `prescribed` | flux          | HVAC, internal/occupancy gains          | `Q_<label>`         |

`exterior`, `ground`, and each distinct `solar` orientation are **singletons** auto-created
as soon as one element needs them. `adjacent` signals are per named neighbour — two
partitions naming `"kitchen"` share one `T_kitchen`; a partition naming `"hallway"` gets its
own. `prescribed` signals are author-created.

The user does not open a "new Signal" dialog. Setting `Window.orientation = S` ensures a
`G_sol_S` signal exists (creating it if absent). The Signal list is a byproduct of authoring
elements with boundaries.

> **Invariant (signal liveness).** A Signal exists in the document iff at least one element
> references it **or** it is `prescribed`. Editing/deleting the last referencing element
> garbage-collects auto-signals.

A Signal *declares* a required input — it does **not** hold the time series. Binding a
Signal to actual data (uploaded CSV column, InfluxDB query, constant/schedule) is a separate
layer deferred to a future version. The Signal's identity fields (`id`, `name`, `kind`,
`role`, `meta`) are kept binding-agnostic so a future `binding` field can attach without
disturbing grouping or ODE names.

---

## The `ModuleType[Signal]` notation

A derived module is fully identified by *(its type, its boundary signal)*:

- `DirectLoss[T_ext]` — lumped conduction to outside.
- `DirectLoss[T_kitchen]` — a *distinct* module: conduction to the kitchen.
- `SolarGain[G_sol_S]`, `SolarGain[G_sol_W]` — south- and west-glazing solar, two modules.
- `HeavyWall[T_ext]` — the R-C-R wall branch to outside.
- `RoomMass` — no bracket; its boundary is `T_room` itself, nothing to disambiguate.

The bracketed signal is the grouping key's second half (see [`40_physics.md`](40_physics.md)
I8): two elements produce the same module iff they share both the `ModuleType` (from their
treatment) and the `[Signal]` (from their boundary).

---

## Elements declare their boundary

Every envelope element carries a **boundary reference** — which signal its outer terminal
couples to.

| Element      | Boundary field(s)                                 | Signal(s) pinned                                      |
| ------------ | ------------------------------------------------- | ----------------------------------------------------- |
| `OuterWall`  | `orientation` (S…N)                               | `T_ext` (conduction) + `G_sol_<orient>` (heavy only)  |
| `Window`     | `orientation` (S…N)                               | `T_ext` (conduction) + `G_sol_<orient>` (solar)       |
| `Floor`      | `boundary` ∈ {ground, adjacent:`<room>`, exposed} | `T_ground` / `T_<room>` / `T_ext`                    |
| `Partition`  | `adjacent` = `<room label>`                       | `T_<room>`                                            |
| `IndoorMass` | — (interior)                                      | — (auto-paired to `RoomMass`; see I4)                 |
| `HeatSource` | `signal` = a `prescribed` flux signal             | `Q_<label>`                                           |

---

## Grouping rule (deterministic, hardcoded)

The assembler derives modules by a **fixed rule** — a pure function of (element type, fields,
treatment, signals pinned). No user routing, no search.

```
for each element e:
    treatment = treatment_of(e)             # forced default, or the heavy/light knob
    for each (form, signal) e contributes under treatment:
        key = (treatment_module_type, signal)
        modules[key].claim(e, channel)      # accumulate element's budget for that channel
emit one module per distinct key
```

- **One module per distinct `(treatment, signal)`.** Two south windows → one
  `SolarGain[G_sol_S]`. A south and a west window → two `SolarGain` modules.
- The module's **prior** is derived from the summed channel budgets of its claimed elements
  ([`40_physics.md`](40_physics.md) I4).
- The (element, channel) exactly-once invariant (I3) is now an internal consistency
  assertion on the rule's output, not a user-facing constraint.

### Treatment menus (the only authoring knob)

| Element             | Treatments                                   | Module(s) produced                                     |
| ------------------- | -------------------------------------------- | ------------------------------------------------------ |
| `OuterWall` (heavy) | **Thermal-mass wall** (default) · Simple loss | `HeavyWall[T_ext]` · `DirectLoss[T_ext]`              |
| `OuterWall` (light) | Simple loss *(forced)*                       | `DirectLoss[T_ext]`                                    |
| `Window`            | Glazing *(forced)*                           | `DirectLoss[T_ext]` + `SolarGain[G_sol_<o>]`           |
| `Floor`             | by `boundary` *(forced)*                     | `GroundLoss[T_ground]` · `DirectLoss[T_<room>]` · `DirectLoss[T_ext]` |
| `Partition`         | Interior loss *(forced)*                     | `DirectLoss[T_<room>]`                                 |
| `IndoorMass`        | Room mass *(forced, auto)*                   | `RoomMass`                                             |
| `HeatSource`        | Prescribed flux *(forced)*                   | `SourceFlux[Q_<label>]`                                |

"Heavy" vs "light" for a wall is decided by whether its layers carry a STORAGE budget
(`is_heavy`). The menu only offers an override on a heavy wall (model it as simple loss
anyway). This is the single binary the user controls; it lives on the **element** card.

> **Extensibility is by adding a rule, not by freewiring.** A future element type with two
> sensible wirings gets a treatment-menu entry and its grouping rule — reviewable, testable,
> physically meaningful.

---

## What the user does, end to end

1. Add an `IndoorMass` (room geometry) → `RoomMass` exists, `C_room` derived.
2. Add elements; each form asks for its boundary (orientation / neighbour / ground). Signals
   auto-appear as needed.
3. For a **heavy** wall, optionally flip its treatment to "simple loss".
4. The **derived topology** (read-only): one branch per `(treatment, signal)` module, labelled
   by its boundary signal. The user reads it; they don't wire it.
5. The **inputs panel** (see [`20_layout.md`](20_layout.md)) lists every signal the model
   needs; the user supplies a series per signal, then simulates.

No "add module", no routing checkboxes. The element×channel matrix survives only as a
collapsible **diagnostic** — the check that the rule produced exactly-once, complete ownership
— which stays quiet unless a `problem` fires.

---

## Open questions

- **Solar transposition per orientation/tilt.** `solar.py` computes POA per orientation; tilt
  is hardcoded vertical. A `G_sol_<orient>` signal should carry its orientation (and
  eventually tilt) in `meta` so the weather→POA step is per-signal. Roofs (tilted) are the
  forcing case. Where derived signals like this sit relative to the topology is not yet
  settled — they could be integrated into the RC topology if linear, hard-coded as in the
  current `SolarGain_{orientation}` approach, or handled as a preprocessing step (e.g.
  `T_soil` requiring yearly data import).
- **Identifiability across split sources.** Splitting `DirectLoss[T_ext]` into
  `DirectLoss[T_ext]` + `DirectLoss[T_kitchen]` adds a parameter. The band rule / lens
  ([`40_physics.md`](40_physics.md) I7) must judge whether two boundary signals are distinct
  enough to separate the two conductances. This is the identifiability question the signal
  split makes concrete.
- **Prescribed signals UX.** HVAC and occupancy gains are the only author-created signals;
  how they're entered (constant, schedule, uploaded series) is a right-column concern, not
  yet settled.
- **Signal → data-source binding (future version).** Mapping each Signal to a real provenance
  — uploaded file column, InfluxDB query, constant/schedule, or a derived chain. Must attach
  a `binding` to a Signal without touching its identity or the grouping. Open: where bindings
  live (on the Signal, or a separate registry shared across models), and how a fit study
  selects a time range over a bound source.
