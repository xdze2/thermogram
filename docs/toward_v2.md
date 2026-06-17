# toward v2 — self-contained spec

> **Status:** the design of record for the v2 rewrite. Greenfield: new code,
> selective salvage from the prototype. This document supersedes the scattered
> design notes — the load-bearing conclusions from `project_design.md` and
> `modeling_pipeline.md` are folded in here; those docs are now historical
> reference for *why*, not *what*.

---

## 1. What this is (and isn't)

A **webapp assistant** to study the thermal properties of a house, room by room,
with an **RC lumped model**. Svelte front + FastAPI/Python back.

- **Is:** an order-of-magnitude reasoning tool for a non-expert homeowner.
- **Is not:** a professional building-simulation suite (no EnergyPlus ambitions).

The whole point is to answer *what-if* questions:

- External shutter on this window — how many °C does it buy?
- Insulate this wall, or fix the window frame first?
- What's the summer-vs-winter comfort trade-off?

The method is the IEA EBC **Annex 58 / 71** philosophy: identify effective
thermal parameters (R, C) of an *existing* building from *in-situ* temperature
measurements. We never know the exact layer geometry of an old wall — only its
effective bulk behaviour is identifiable from data. The model is built around
that fact, not in spite of it.

---

## 1b. The focused use case: the room balance sheet

The solver is dimension-agnostic — one room or twenty, it's the same RC network.
The **UI is not**: every concept the UI exposes has to be named and laid out, so
generality is cheap in the solver and expensive in the interface. The lever for
"stay focused" is therefore **constraining what the UI is allowed to talk
about**, not constraining the model.

So v2 has one framing:

> **Pick one room. Report everything from that room's point of view** — where
> heat leaves, where it enters, how fast, through what — as a single
> *balance sheet*. The rest of the house exists in the solver (adjacent rooms
> are boundaries or coupled masses) but is **never the primary view.**

The four outputs we care about are not four features — they are the four terms
of one room's steady-periodic energy balance, decomposed by path:

| Output | Static (no solve) | Dynamic (needs the mesh) |
|---|---|---|
| **R to exterior**, per element | `R_total`, `U·A` (ISO 6946) | periodic transmittance, dynamic share |
| **Solar gain** ± shading | g·A·I incidence | phase-shifted gain via wall lag |
| **Thermal lag** | — | decrement factor, time shift (ISO 13786) |
| **Loss to ground / adjacent** | `U·A` to each boundary | coupled-mass dynamics |

### ISO vocabulary is the fixed output language

The reported quantities are **named ISO quantities**, not ad-hoc metrics. This
*is* the constraint: the UI may only show something that has a standard name and
a standard formula.

- **Static** — ISO 6946: `R_si`, `R_se`, `R_total = R_si + Σ(d/λ) + R_se`,
  `U`-value, areal heat capacity. Pure algebra on the layer stack; the prototype
  already computes this in `physics.py`. **No solve needed** — and the per-room,
  per-element decomposition is the first thing the balance sheet shows.
- **Dynamic** — ISO 13786 (the periodic companion to 6946): periodic thermal
  transmittance, **decrement factor**, **time shift** (= "thermal lag"). These
  are exactly what the RC mesh produces on top of the static numbers, evaluated
  at the 24 h period (the `ω` already used for `chain_n`).
- **Solar** — a source term on the wall/window outer node (already in the mesh);
  shading toggles the incident flux.

This keeps the analysis rigorous and testable (every output is a named formula
with a reference) and legible to anyone who's seen a building-physics spec,
while the solver underneath stays fully general.

**UI consequence:** the primary view is **one selected room's balance sheet**.
A room switcher selects which room is "in focus"; the house topology is editable
(elements, adjacencies) but framed as *this room and its neighbours*, not as a
whole-house diagram. This is what the §7 vertical slice must produce for its one
room, and what the deferred three-column UI (§9) eventually wraps.

---

## 2. The core architecture: three layers, two arrows

Everything below follows from one idea. Three representations, related by **two
arrows of fundamentally different nature**:

```
(1) Physical graph  ── coarsen ──▶  (2) Toy model    ── mesh ──▶  (3) Atomic graph
    full detail        lossy,           minimal,        lossless,    Laplacian,
    user's house       semantic         fit-facing      mechanical   solver-only
```

- **Coarsen (1→2)** is **lossy and a modeling decision.** Output is *smaller*:
  merge the three south windows that can't be told apart, fold a negligible
  thermal bridge into its neighbour. This is where **identifiability and
  uncertainty** live.
- **Mesh (2→3)** is **lossless and mechanical.** Output is *larger*: a heavy
  wall becomes N RC lumps to capture its 24 h lag. A pure function of the toy
  element plus a discretization choice, governed by a **conservation contract**.

Detail goes **rich (1) → minimal (2) → exploded (3)**: down, then up. That
asymmetry is the reason (1) and (2) share one data structure while (3) is a
different one. **The two arrows must never share a mechanism** — conflating them
is the central mistake the prototype made (three different resistance-chain
walks; see §8).

### 2.1 Why (1) and (2) are the same structure

Coarsening must be **closed over the type**: merging three windows must yield *a
window* (2 terminals, a conductance) so it can be merged again or handled
uniformly downstream. So (1) and (2) share a type, related by a **containment
hierarchy**: a layer-2 element *contains* a subgraph of layer 1. The physical
model is the fully-expanded leaf level; **the toy model is a *cut* across the
hierarchy at a chosen depth.**

- Default cut: shallow — one toy element per physical element.
- Aggressive cut: deeper — south windows collapsed into one.
- **The fit only ever sees the cut.** Detail below the cut is folded, never lost.

### 2.2 Why (1)/(2) are type-A and (3) is type-B

| | Type A (netlist / hypergraph) | Type B (Laplacian / nodal admittance) |
|---|---|---|
| Components | first-class, *n* terminals, may hold internal state | — |
| Nodes | named connection points (rooms, boundaries) | masses (C to one ground) |
| Edges | — | 2-terminal conductances, **no state** |

Layers (1)/(2) **must be type A** because:

1. **Between-elements carry internal state.** A heavy wall is an RC *chain* (R
   *and* C) sitting *between* two rooms. Type B can't place it — edges have no
   C, nodes don't sit between two nodes. It's irreducibly a **2-terminal device
   with internal state.**
2. **Sources are multi-terminal.** One solar input feeding several windows is
   one component with many terminals; type-B edges are strictly 2-endpoint.

Layer (3) is type B because *after meshing* neither property survives: every
atom is a pure mass-to-ground or a pure 2-terminal conductance. Type B is the
natural and only place for the solver.

**Convention:** rooms + boundaries are the *nodes*; walls / windows / air-
exchange / sources are the *components* (hyperedges). Matches how the house
already thinks (`between: [roomA, roomB]`).

### 2.3 The recursive element type

```text
Element:                  # shared by layers (1) and (2)
  id
  kind:      room | wall | window | air_exchange | source | boundary | group
  terminals: [node refs]          # 1 room/source-to-one, 2 wall, n shared source
  params:    {R_eff, C_eff, gain_eff, ...}   # effective physics AT THIS level
  prior:     (nominal, sigma) per param       # belief; WIDENED when detail dropped
  children:  [Element] | None     # finer model this summarizes; None at leaves
  combine:   rule                 # how children roll up into this element:
                                  #   series_sum | parallel_inv_sum |
                                  #   parallel_sum | chain | identity
```

- **Physical (1)** = leaf level, `children=None`, params from geometry+materials.
- **Toy (2)** = a frontier cut; some elements expanded, some collapsed with a
  `combine` roll-up.
- **Belief is first-class:** every param carries `(nominal, sigma)`. A "run" is
  just a fit with every sigma → 0 (fixed). There is **no separate run path.**

---

## 3. The two contracts (these are assertions, not prose)

Each arrow has exactly one contract. In the prototype these were the bugs; here
they are postconditions that fail loudly.

### 3.1 Coarsening contract (1→2)

- **Nominal roll-up** — parent nominal = combine of child nominals:
  | rule | roll-up |
  |---|---|
  | `series_sum` | `R_parent = Σ R_child` |
  | `parallel_inv_sum` | `1/R_parent = Σ 1/R_child` |
  | `parallel_sum` | `C_parent = Σ C_child` |
  | `chain` | `(R,C)_parent = (Σ R, Σ C)_child` |
  | `identity` | single child passthrough |
- **Invertibility** — every rule is an `(expand, reduce)` pair satisfying
  `reduce(expand(φ)) == φ`. This is what makes the prototype's "R shown ≠ R
  fitted" mismatch structurally impossible.
- **Sigma widening** — when detail is *dropped* (not merely merged), the parent
  sigma must be **≥** the rolled-up child sigma, widened to absorb the unmodeled
  physics. *(Policy per coarsening kind is the one open design item — see §9.)*

### 3.2 Meshing contract (2→3) — conservation

For each cut-level element the mesher emits type-B atoms such that:

- **R conserved:** `Σ R_atom` along a series path `== R_eff`.
- **C conserved:** `Σ C_atom == C_eff`.
- **Source gain conserved:** `Σ gain_atom == gain_eff` across fanned terminals.

This makes the prototype's `chain_n=1` bug (a wall emitting only `Rse+Rsi` and
dropping its bulk `R_wall`) a failed assertion: an N=1 mesh that omits the bulk
R violates `Σ R_atom == R_eff`.

The **mesher is the type-A → type-B compiler** — the *only* component that knows
about atoms. Edit and fit the schematic (type A); simulate the matrix (type B).
Nobody edits the matrix; nobody simulates the schematic.

---

## 4. φ, identifiability, the cut

- **φ lives directly on cut-level element params** (`wall.R_eff`, `wall.C_eff`).
  No projection layer, no group-of-atoms indirection. The thing the fit
  optimizes *is* the thing shown on the card.
- **Identifiability *is* choosing the cut.** "These south windows can't be
  separated" → cut above them. The merge is a graph rewrite on the small
  semantic graph, not a heuristic walking the atomic mesh.
- **Cut granularity (identification) ⊥ mesh granularity (dynamics).** Fit a
  coarse "south windows" group while still meshing a heavy wall finely for lag.
- **Fold-back is a *selection*, not an inversion.** The fit holds the effective
  params, the mesher regenerates atoms, the solver runs, and only *observable*
  quantities map back up (room T = room-air atom T; internal lump temps
  discarded). You never invert the mesh — you already hold the params.

---

## 5. The solver (layer 3)

- **Type B, transient, never stored.** Regenerated by the mesher on every
  sim/fit iteration.
- **Assembly = Laplacian stamping:** `Y[i,i] = Σ G_ij`, `Y[i,j] = -G_ij`. No
  resistance-node elimination, no chain-walking — resistances were never nodes.
- **Two solvers, same assembled system:**
  - `simulate_ivp` (BDF) — handles stiffness (≈30× C ratio thick-wall vs air);
    for verification.
  - `simulate_zoh` — exact matrix-exponential step for piecewise-constant
    inputs on a uniform grid; required for fit/MCMC. **(salvage from prototype)**
- **Fit:** params in **log-space** (guarantees R,C > 0), log-normal priors as
  extra residuals. One path: `least_squares` (NLS) and optional `emcee` (MCMC)
  share the same `build_forward` closure. **A "run" = a fit with all params
  fixed.**

---

## 6. Data model

**House JSON is the sole source of truth.** Layers (2) and (3) are derived.
What's stored:

```json
{
  "name": "maison_test",
  "rooms":    [ /* layer-1 leaf elements: geometry + obs signal */ ],
  "elements": [ /* layer-1 leaf elements: walls, glazing, air-exch, boundaries */ ],
  "cut":      { /* layer-2: chosen frontier + coarsening choices + per-param mode/prior */ },
  "studies":  [ /* config + result record only; never the derived model */ ]
}
```

- **Material library** `data/materials/*.json` — `{lambda, rho, cp}` + source.
  **(salvage as-is; it's good and well-sourced)**
- **Staleness** via a model hash (SHA-256 of canonical layer-1 JSON, first 12
  hex), stored on each result, recomputed on load. **(salvage the idea)**
- **Signals separate from topology.** Study maps `node_id → signal_name`; data
  fetched at runtime, resampled to a uniform grid.

### Data sources (simplified vs prototype)

The prototype hard-depended on InfluxDB. v2 is **file-first**: CSV / Parquet
import is the primary path (easy to test, no live dependency), with open-meteo
fetch for weather. InfluxDB becomes one optional adapter behind a common
`fetch(signal, start, end) → series` interface, not a hard requirement.

---

## 7. First milestone — full vertical slice

One room, one wall, one window, end to end, exercising **every** layer and both
arrows. Thin but complete:

1. **Describe** (layer 1): a room (volume → C), one opaque wall (layer stack →
   R_total, C, chain_n via `δ = √(2α/ω)` at 24 h), one window (U·A + solar),
   one outdoor boundary. *(salvage the ISO-6946 formulas from `physics.py`.)*
2. **Coarsen** (1→2): default shallow cut — one toy element each. Assert the
   roll-up + invertibility contract on this trivial cut.
3. **Mesh** (2→3): emit atoms; assert the conservation contract (the N=1 wall
   must still carry its bulk R).
4. **Fit:** load a CSV of measured indoor T + weather; fit `(R_wall, C_wall)`
   with everything else fixed; ZOH forward, NLS, log-space.
5. **Report the room balance sheet** (§1b) for the one room: per-element
   `R_total`/`U·A` and the room's areal heat capacity (ISO 6946, static), plus
   the wall's decrement factor + time shift (ISO 13786, from the mesh). This is
   the *focal deliverable* — the slice exists to produce one legible balance
   sheet, not just a fitted number.
6. **Answer one what-if:** change the window U-value, re-simulate, report the
   °C delta on indoor T and the change in the balance sheet.

Acceptance: the slice runs end-to-end from a house JSON + a CSV, both contracts
assert green, the balance sheet reports named ISO quantities, and the what-if
produces a sane number. **No** agent loop, **no** sigma-widening yet (default
sigma), **no** three-column UI — minimal UI or even a notebook is fine for this
milestone.

---

## 8. Salvage list (greenfield, selective)

| Salvage as-is / lightly | Rewrite under new architecture | Drop entirely |
|---|---|---|
| `data/materials/*.json` | layer-1 → layer-2 → layer-3 pipeline | `identifiability.py` (cut replaces it) |
| ISO-6946 R/C/`chain_n` formulas (`physics.py`) | element data model (recursive type) | `view.py` chain-walking |
| `simulate_zoh` / `simulate_ivp` numerics | `assemble` as pure Laplacian stamping | legacy/dual fit paths (`todo_1` #5/#6) |
| model-hash staleness idea | `fit` on the effective layer | run-vs-fit split |
| log-space fit + log-normal priors | mesher as the sole atom-aware component | InfluxDB as a hard dependency |

What the new architecture *structurally prevents* (the prototype's `todo_1`
bugs): chain_n=1 dropping bulk R; `log(0)=-inf` priors; R-shown ≠ R-fitted;
boundary/outdoor confusion; triple-implemented chain walks.

---

## 9. Deliberately deferred (NOT in v2 core)

Keep these out until the three-layer core + vertical slice is solid:

- **The agent loop** and beliefs/atoms/pseudos/insight machinery from
  `modeling_pipeline.md` — heavy, mostly unimplemented, premature.
- **Hot-path/cold-path split + frozen `SystemTemplate`** from
  `implementation.md` — a performance optimization; correctness first.
- **Three-column desktop UI** (`todo_2.md`) — good direction, but a UI rework
  is its own milestone after the core works.
- **Energy view, per-lump avg-W, MCMC at scale, persistent Parquet results** —
  roadmap items, post-core.

## 10. The one open design item

The **sigma-widening policy** (§3.1): exactly *how much* to widen a prior when a
detail is dropped vs. merged. It's the uncertainty analogue of the meshing
conservation contract and what makes "the toy model is an honest simplification"
*testable*. Specify it per coarsening kind (merge vs. drop-and-fold) before
implementing the coarsen arrow beyond the trivial default cut. Not needed for
the §7 vertical slice (default sigma is fine there).
