# 20 — UI Layout

**Status: BUILT.** The layout refactor landed (commit `3259ea0`); the 3-tab layout is gone,
replaced by the 2-column split described here. The topology panel shows the server-rendered
schemdraw schematic (commit `b47d815`); the app is now multi-model with a home page (see
[`10_state.md`](10_state.md)). The [§Resolved divergences](#resolved-divergences) section
records what this replaced. Treat this document as describing existing behavior.

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

- **Left-top — Elements.** The element cards + add/edit/delete (today's `ElementList`).
- **Left-bottom — Topology.** The server-rendered star schematic, the module list, and the
  routing controls — "the structure of the assembled model."
- **Right-top — Time range & signals.** Simulation window and input/scenario selection.
- **Right-bottom — Graphs.** `T_room` (and other states) time series; parameter / flux
  views (today's `ParameterTable` content folds in here).

## The routing matrix is a diagnostic, not a primary surface

The element × channel matrix is how you *check* that ownership is exactly-once and complete
— it is a **diagnostic**, not where the user does their authoring. Authoring is: add
elements, add modules, tick which elements a module claims. So:

- The matrix lives **under the topology**, in a **collapsible "Ownership check" panel**, not
  at tab-level prominence.
- It draws attention only when it must: if `assembly.problems` is non-empty (a double-count
  or unclaimed channel), the panel auto-expands and the offending cells are flagged. When the
  room is clean, it stays collapsed and quiet.

## Routing controls must respect channel compatibility

This is a correctness requirement on the routing UI, not just aesthetics. A module can only
own channels in its `owns` set; offering to route an element that shares no channel with the
module presents a physically meaningless control.

> **Rule.** For a given module `m` and element `e`, show a routing control **only if**
> `m.owns ∩ {channels e actually offers a budget for} ≠ ∅`.

- `e`'s offered channels = the keys of `e.budgets` whose budget has at least one non-null
  field (the matrix already computes this `hasBudget` test).
- `m.owns` is already in the registry payload (`module_types[].owns`) — **no backend change
  is needed**; the frontend simply must use it.
- **`RoomMass` owns nothing and takes no elements.** Its card shows its `floor_area` field
  and **no** element checkboxes at all. (Routing a Window into RoomMass is already a no-op
  server-side; the UI must not offer it.)

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

- [x] No top-level tabs; Elements, Topology, Time-range, and Graphs are simultaneously
      reachable on a large screen.
- [x] Editing an element on the left visibly updates the topology and the right-hand graphs
      without navigation.
- [x] The routing matrix is collapsed by default and auto-expands when `problems` is
      non-empty.
- [x] A module never shows a routing control for an element it cannot own; RoomMass shows no
      element checkboxes.
- [x] Columns stack (not hide) on narrow widths.
