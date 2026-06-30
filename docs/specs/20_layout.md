# 20 — UI Layout

**Status: PARTLY BUILT.** The 2-column split (commit `3259ea0`), server-rendered schematic
(`b47d815`), and multi-model home page are built and current. **The authoring model is
mid-change**, per [`15_signals_and_grouping.md`](15_signals_and_grouping.md): the left column
must move from "add modules + tick element×channel cells" to **per-element-type forms whose
fields include the element's boundary**, with the **topology and modules derived (read-only)**
and a **generated inputs panel**. Sections below tagged **[§15-pending]** describe that target;
where they conflict with the still-built routing-matrix behavior, `15` wins.

---

## The problem with tabs

The room is **one connected causal chain**: editing an element changes routing → changes
the assembled parameters → changes the simulation. Tabs slice that chain into three screens
and hide two-thirds of it at any moment, so the user cannot see cause and effect. The first
UI test confirmed it "feels hard to understand" for exactly this reason.

## Target: a single-page, 2-column split

thnodes is a **large-screen, single-user** tool. Use the width. One page, no top-level tabs.
The left column is **what the room *is*** (authoring / structure); the right column is **how
it *behaves*** (results). Cause sits on the left, effect on the right, both visible at once.

```
┌───────────────────────────── header (title, loading, refresh) ──────────────────────────┐
├─────────────────────────────────────────┬───────────────────────────────────────────────┤
│ LEFT — authoring / structure            │ RIGHT — behavior / results                    │
│                                         │                                               │
│  ┌─ Elements ───────────────────────┐   │   ┌─ Time range & signals ───────────────┐    │
│  │ element cards; + Add element      │   │   │ range selector, scenario / signals    │    │
│  │ (edit / delete inline)            │   │   │                                       │    │
│  └───────────────────────────────────┘   │   └───────────────────────────────────────┘    │
│                                         │                                               │
│  ┌─ Topology ───────────────────────┐   │   ┌─ Graphs ──────────────────────────────┐    │
│  │ star schematic (server SVG)       │   │   │ T_room (+ states) time series         │    │
│  │ modules + routing controls        │   │   │ flux / parameter views                │    │
│  │ ▸ Ownership check (collapsible)   │   │   │                                       │    │
│  └───────────────────────────────────┘   │   └───────────────────────────────────────┘    │
└─────────────────────────────────────────┴───────────────────────────────────────────────┘
```

- **Left-top — Elements.** The element cards + add/edit/delete. Each element form carries its
  **boundary** field(s) (orientation / adjacent-room / ground…) and, for a heavy wall, its
  **treatment** toggle. **[§15-pending]** This is now the *only* authoring surface — there is
  no "add module" form and no routing control here.
- **Left-bottom — Topology.** The server-rendered star schematic + a **derived, read-only**
  module list (one branch per `(treatment, signal)`, labelled by its boundary signal).
  **[§15-pending]** Read, don't wire. The "Ownership check" matrix stays as a collapsible
  diagnostic beneath it.
- **Right-top — Time range & signals.** Simulation window + the **inputs panel generated from
  the assembly**: one entry per `Signal` the derived modules require (`T_ext`, `T_kitchen`,
  `G_sol_S`, `Q_hvac`…), each needing a series or scenario. **[§15-pending]**
- **Right-bottom — Graphs.** `T_room` (and other states) time series; parameter / flux
  views (today's `ParameterTable` content folds in here).

## Authoring is element forms; the matrix is a diagnostic **[§15-pending]**

Under [`15_signals_and_grouping.md`](15_signals_and_grouping.md), **authoring is: add
elements, set each element's boundary, and (for a heavy wall) pick its treatment.** Modules
are *derived*; the user neither adds them nor routes elements into them. The element × channel
matrix is therefore **purely a diagnostic** — the *check* that the grouping rule produced
exactly-once, complete ownership.

- The matrix lives **under the topology**, in a **collapsible "Ownership check" panel**, not
  at primary prominence.
- It draws attention only when it must: if `assembly.problems` is non-empty (which now means
  an **engine bug** in the rule, not a user mistake — see [`40_physics.md`](40_physics.md)
  I3), the panel auto-expands and the offending cells are flagged. When the room is clean, it
  stays collapsed and quiet.

> **Resolved by the direction change.** The old "show a routing control only if `m.owns ∩ e`'s
> offered channels ≠ ∅" rule, and the per-element routing checkboxes it governed, are
> **removed** — there are no routing controls to filter. Their correctness concern (never
> present a physically meaningless wiring) is now satisfied *by construction*: the grouping
> rule only ever produces meaningful `(treatment, signal)` modules.

- **The room.** `IndoorMass` is an element with geometry fields (`a, b, c`, `furniture`); the
  assembler auto-pairs it to `RoomMass` (derived). No RoomMass card to author, no routing.

## Every shown value carries its physical unit

This is a correctness-of-communication requirement, not decoration. A thermal model is a pile
of quantities in different orders of magnitude (J/K, W/K, m, W/m²); a bare number is
ambiguous and invites the user to mis-enter or mis-read it.

> **Rule.** Every numeric value the UI **displays or accepts** — element fields, derived
> budgets, module parameters/priors, simulation outputs, axis labels — is shown with its SI
> physical unit.

- **Inputs:** the unit appears next to the field (label suffix or input-group addon), e.g.
  `a [m]`, `b [m]`, `c [m]`; `area [m²]`, `U [W/(m²·K)]`, `thickness [m]`.
- **Derived budgets / parameters / priors:** shown with units too — `UA [W/K]`,
  `C [J/K]`, `C_room [J/K]`, `H_in [W/K]`, `shgcA [m²]`.
- **Graphs:** every axis is labelled with its unit (`T_room [°C]`, flux `[W]`, time `[h]`).
- **Source of truth:** units are a property of the quantity, not the widget. The unit for a
  field/param/budget-key should come from a single shared map (so `UA` is always `[W/K]`
  everywhere it appears), not be re-typed per component. `furniture` and other enums are
  unitless and show no unit.

## Responsiveness

The 2-column split is the large-screen target. Below a width threshold (e.g. `lg`), the two
columns stack vertically (left column first: Elements, Topology, then Time range, Graphs).
No information is hidden behind tabs at any width — narrow screens scroll.

## Resolved divergences

These were the violations the refactor fixed; all resolved:

| Where | Was (wrong) | Now |
| ----- | ----------- | --- |
| `App.svelte` | 3 top-level tabs; only one third of the causal chain visible at a time. | Single-page 2-column split; nothing hidden behind tabs. |
| `ModuleGraph.svelte` routing matrix | A top-level section with its own heading, always shown. | Collapsible "Ownership check" diagnostic under the topology; auto-expands only on problems. |
| `ModuleGraph.svelte` routing checkboxes | A checkbox rendered for **every** element under **every** module, ignoring `owns` (so RoomMass offered to route a Window, etc.). | Filtered by `m.owns ∩ e`'s offered channels; RoomMass shows no element checkboxes. |

## Acceptance checklist

Built (layout):
- [x] No top-level tabs; Elements, Topology, Time-range, and Graphs are simultaneously
      reachable on a large screen.
- [x] Editing an element on the left visibly updates the topology and the right-hand graphs
      without navigation.
- [x] The routing matrix is collapsed by default and auto-expands when `problems` is
      non-empty.
- [x] Columns stack (not hide) on narrow widths.

Pending — signal-grouping direction (**[§15-pending]**):
- [ ] No "add module" form and no routing controls anywhere in the edit loop; modules are a
      derived read-only list.
- [ ] Every element form exposes its boundary field(s) (orientation / adjacent-room / ground);
      a heavy wall exposes its treatment toggle.
- [ ] The right-column inputs panel is **generated** from the assembly's required `Signal`
      set (one entry per signal the derived modules demand).
- [ ] Every displayed/accepted numeric value carries its SI physical unit (inputs, derived
      budgets, parameters/priors, graph axes); units come from one shared map, not per-widget.
