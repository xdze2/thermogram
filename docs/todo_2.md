# todo_2 — lumped-element cards → three-column desktop layout

Brainstorm note, not a committed spec.

---

## Done: RC Graph tab → lumped-element cards

The original complaint (see git history of this file) was that the **RC
Graph** tab rendered the *atomic* `expand()` mesh — one box per RC node,
no grouping by physical element — while the actual fit interface
(free/fixed, nominal editing, posteriors) lived in a separate component
(`FitPanel.svelte`'s `phi-table`) reading a separate endpoint. Two
renderings of the same `View` data that could drift.

Shipped:

- `ui/src/lib/LumpedView.svelte` — new component, one card per
  `LumpedElement` (`thermogram/solver/view.py::build_default_view()`'s
  output), sourced from `/houses/{name}/studies/{id}/view`. Cards show
  label, kind badge, `node_a ↔ node_b`, editable nominal R/C with
  `sigma_log`, and a free/fixed toggle. Verified against a real study
  (`maison_test`) via direct API calls: `POST .../view` returns the
  expected `Req`/`Ceq`/`T_boundary`/`Q_source` mix, `PUT .../view` persists
  mode toggles and nominal edits correctly.
- Cards are **grouped by `node_a`** for display only (`groupby`, no new
  editable structure) — gives the "everything hanging off `Extérieur`"
  clustering without a second tree.
- RC Graph tab (`+page.svelte`) now requires a selected study: shows
  `LumpedView` when `selectedStudyId` is set, an empty-state prompt
  otherwise ("select or create a study"). The old atomic dagre graph
  (`GraphView.svelte`) survives behind a "debug: atomic mesh" toggle.

Deliberately deferred:

- **avg-W per card.** Needs either a steady-state network solve from
  nominal φ + mean boundary conditions, or aggregating an existing run's
  results per lump's atoms — neither is derivable from one `LumpedElement`
  in isolation. Not yet started.
- **FitPanel's `phi-table`.** Still lives in `FitPanel.svelte`, unchanged,
  duplicating what `LumpedView` now also renders. Chosen deliberately as
  the smaller, reversible first step. Two real options once the card view
  has been used for a while:
  - strip `phi-table` out of `FitPanel`, leaving it as just run/fit
    controls + result charts reading selection from the cards;
  - or fold run/fit controls *into* `LumpedView` directly and retire
    `FitPanel` as a separate component.
  The second option is closer to where the layout direction below ends up
  (cards as the one and only fit interface), so probably don't invest in
  the first if the three-column rework happens soon after.

---

## Next: three-column desktop layout

Separate, larger idea — came up when asked "starting from scratch, what
should the whole app look like" rather than "what's wrong with one tab."
Current `+page.svelte` is tab-switched (`rc` / `studies` / `sim`): you
can't see the house elements, the φ-space cards, and the result graphs
at the same time, which re-creates a milder version of the original
two-sources-of-truth problem — you edit in one tab, then tab away to see
the effect.

Proposed: replace the tabs with three persistent columns for the `house`
section, desktop-only target (no attempt at responsive/mobile):

```
┌─────────────────────────────────────────────────────────────────────────┐
│  House: maison_test          [study: Jan cold snap ▾]    ⚠ stale  [Run]  │
├───────────────┬─────────────────────────────────┬─────────────────────┤
│ ELEMENTS       │  LUMPED VIEW                     │  TIME RANGE          │
│ (geometry)     │  (cards, grouped by node_a)       │  ┌─────────────────┐│
│                │                                   │  │ wk│mo│yr│custom  ││
│ ▸ Rooms        │  Chambre ──────────────           │  │ ◂ 2026-01 ▸     ││
│   Chambre      │  [Req] Wall NE+win+N   0.032 free  │  └─────────────────┘│
│ ▸ Walls        │  [Ceq] Chambre mass    108648 free │                     │
│   Wall NE      │                                   │  ────────────────── │
│   Wall N       │  Extérieur ────────────           │  GRAPHS             │
│   Wall SE  ⚠   │  [T_bnd] Extérieur     fixed       │  ┌─ Weather ───────┐│
│ ▸ Glazing      │                                   │  │ T_out, solar     ││
│   win           │  win ──────────────────           │  └─────────────────┘│
│ ▸ Air exch.    │  [Q_src] win solar     fixed       │  ┌─ Temperatures ──┐│
│                │                                   │  │ sim vs obs       ││
│ [+ add element]│  [⚠ Rebuild]  [Run fit]            │  └─────────────────┘│
│                │                                   │  ┌─ Power flux ─────┐│
│                │                                   │  │ per-lump avg W   ││
│                │                                   │  └─ Residuals ─────┘│
└───────────────┴─────────────────────────────────┴─────────────────────┘
```

- **Left = elements** (today's `HousePanel`) — geometry/topology editing,
  the house JSON source of truth. Unchanged role, just docked permanently
  instead of living in its own pane.
- **Center = lumped view** (`LumpedView.svelte`, this session's work) —
  the φ-space / fit interface. Run + fit controls move here (currently in
  `FitPanel`), since the cards are already "the one place that edits a
  `LumpedElement``" per the section above.
- **Right = time range + graphs**, stacked vertically — one global range
  control (week / month / year / custom dates) feeding both the displayed
  graphs *and* whatever run/fit request goes out. Decided against a
  separate "browse range" vs "fit range": one shared `range`, matching
  `FitPanel`'s current prop (it already threads one `range` everywhere).
  Graphs: weather (T_out, solar gain), temperatures (sim vs observed),
  power flux (per-lump avg W, once that's built), residuals.

**Cross-linking, left ↔ center.** Selecting a geometric element on the
left highlights the card(s) that `realizes` it in the center column, and
vice versa — bidirectional. Built from data that already exists
(`LumpedElement.realizes` is the house element uuid; `LumpedElement.atoms`
are the atomic node ids), so this is wiring a shared "selected id" state
across two existing components, not new backend work. Note a `Req` that
merges several elements (`realizes: null`) has no single left-side target
to highlight back to — falls out naturally, nothing special to handle,
just no highlight in that case.

### Open questions before implementing

- **Run/fit controls' new home.** Moving them from `FitPanel` into
  `LumpedView` (or a thin strip above/below the card grid) is the natural
  conclusion of "cards are the one fit interface" — but `FitPanel` also
  owns the input-signal health-check preview and the result charts
  (`SimCharts`). Those result charts are exactly what's proposed for the
  right column. Likely split: `LumpedView` gains run/fit buttons + signal
  preview; chart rendering moves to the right column, fed by the same
  `simResult`/`fitResult` state. Needs `+page.svelte` (or a new shared
  store) to hold that state instead of it living inside `FitPanel`.
- **Per-study vs per-house framing.** Today everything (`View`, runs,
  fits) is scoped to a `study`. The three-column layout reads as "the one
  view of this house," but the center/right columns are actually showing
  *one selected study's* φ-space and results. Needs a visible study
  switcher (sketched top bar above) rather than implying there's one
  canonical view per house.
- **Column widths / overflow.** Element lists and card grids can both get
  long (many rooms/walls; many lumps). Each column needs independent
  scroll; no global page scroll. Probably fine with `overflow-y: auto` per
  column (already used in `LumpedView.svelte`), but worth checking with a
  house that has 10+ rooms before committing to fixed column widths vs.
  resizable splitters.
- **Where this leaves `GraphView`'s atomic debug mode.** Was pushed behind
  a toggle inside the center column for the tab version. In a three-column
  layout, does atomic-mesh debugging deserve its own narrow toggle inside
  the center column (current approach, keeps working), or a temporary
  full-width overlay/modal since the dagre graph wants more horizontal
  space than one of three columns gives it? Leaning: modal/overlay,
  triggered from the center column's debug toggle — the atomic mesh is a
  debugging tool, not a layout citizen.
- **Scope/sequencing.** This is a bigger change than the card-view swap
  (touches `+page.svelte`'s top-level structure, not just one tab's
  content). Worth doing as its own reviewable step rather than folding
  into further card-view polish — e.g. land FitPanel's eventual
  simplification first (see "Deliberately deferred" above), *then* the
  column rework, so the run/fit-controls relocation only happens once.
