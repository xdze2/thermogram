# Project design — layered model architecture

> Status: **design note**, not current implementation. This captures the target
> data-model architecture for thermogram, derived from a review of the existing
> `thermogram/solver` code and a redesign discussion. See `docs/todo_1.md` for
> the concrete bugs in the current code that this design is meant to make
> structurally impossible.

## The core idea

Three layers, related by **two arrows of different nature**:

```
(1) physical graph   ── coarsen ──▶  (2) toy model        ── mesh ──▶  (3) atomic graph
    (full detail)      (lossy,         (minimal, fit-       (lossless,    (Laplacian,
     user's house)      semantic)       facing)              numerical)     solver)
```

- **(1)→(2) — coarsening / aggregation.** Lossy. A *modeling decision*. Output
  is *smaller* than input: drop the negligible window, merge the south windows
  (can't be identified separately), don't model a thermal bridge explicitly.
  This is where **identifiability and uncertainty** live.
- **(2)→(3) — meshing / refinement.** Lossless. *Mechanical*. Output is *larger*
  than input: a heavy wall becomes N RC lumps to capture its 24 h thermal lag.
  Pure function of the toy element + a discretization choice, governed by a
  **conservation contract**.

Detail goes **rich (1) → minimal (2) → exploded (3)**: down, then up. That
asymmetry is why (1)/(2) share one structure and (3) is a different one.

The two arrows are **not the same operation** and must not share a mechanism —
conflating them is the central mistake this design avoids.

---

## Why (1) and (2) are the same data structure

Coarsening must be **closed over the type**: merging three south windows into one
effective window must yield *a window* (2 terminals, a conductance), so it can be
merged again or treated uniformly downstream. If coarsening produced a different
kind of object than its inputs, coarsenings couldn't compose.

Therefore (1) and (2) share a type, related by a **containment hierarchy**: an
element in (2) *contains* (is realized by) a subgraph of (1). The physical model
is the fully-expanded leaf level; **the toy model is a *cut* across the
hierarchy at some depth.**

- Default cut: shallow — one effective element per physical element.
- Aggressive cut: deeper — south windows collapsed to one effective element.
- **The fit only ever sees the cut.** Physical detail below the cut is never
  lost, just folded above it.

This generalizes the "one depth of grouping" idea in the current `view.py`: a
**View is a chosen cut through the containment hierarchy.**

---

## Why the (1)/(2) layer is a *type-A* hypergraph (not type B)

Two standard conventions for RC networks:

- **Type A — components-as-nodes / nets-as-wires** (SPICE netlist; hypergraph +
  Modified Nodal Analysis). Components are first-class, may have any number of
  terminals, may carry internal state. Wires carry no physics.
- **Type B — nodes-as-masses / edges-as-conductances** (weighted graph / nodal
  admittance matrix = graph Laplacian). A node has a potential + optional
  capacitance *to a single common reference*; an edge is a 2-terminal
  conductance with no state.

For **thermal** lumped models, capacitance is *always* to one reference
(absolute temperature / "ground"), never between two arbitrary nodes — there is
no "thermal capacitor between the living room and the kitchen." That makes
type B the natural fit **for the atomic layer**, where every primitive really is
a pure mass-to-ground or a pure 2-terminal conductance.

But the **effective / toy layer cannot be type B**, for two reasons:

1. **Between-elements carry internal state.** A heavy wall is an RC *chain* —
   both R and C — sitting *between* two rooms. Type B can place it neither on an
   edge (edges have no C) nor on a node (nodes don't sit between two nodes). It
   is irreducibly a **2-terminal device with internal state**.
2. **Sources can be multi-terminal.** A solar input feeding several windows is
   one component with *many* terminals. Type B edges are strictly 2-endpoint.

Both properties demand **type A** for layers (1) and (2). Type B only earns its
place *after* meshing (layer 3), where neither property survives.

### Rooms-as-nodes convention

Within type A, we choose: **rooms + boundaries are the nodes** (the named points
everything connects to); **the between/attached elements are the components**
(the hyperedges). This matches how `house.json` already thinks (`between:
[roomA, roomB]`) and avoids inventing a separate "net" object per room.

So the (1)/(2) structure is a **hierarchical type-A hypergraph**: nodes = rooms +
boundaries; components = walls / windows / air-exchange / sources, each with a
terminal arity and owned parameters, each optionally containing finer children.

---

## The recursive element type

```text
Element:                      # the recursive type shared by layers (1) and (2)
  id
  kind:        room | wall | window | air_exchange | source | boundary | group
  terminals:   [node refs]            # 1 for a room/source-to-one, 2 for a wall,
                                      #   n for a shared source
  params:      {R_eff, C_eff, ...}    # the effective physics AT THIS level
  prior:       (nominal, sigma) per param   # belief; WIDENED when detail is dropped
  children:    [Element] | None       # the finer model this summarizes; None at
                                      #   physical leaves
  combine:     rule                   # how children's params roll up into THIS
                                      #   element's params (series_sum,
                                      #   parallel_inv_sum, parallel_sum, chain, identity)
```

- **Physical model (1)** = leaf level; `children = None`; params from geometry +
  materials.
- **Toy model (2)** = a frontier cut; some elements expanded to children, some
  collapsed to a single effective element with a `combine` roll-up.
- **Dropped element** = a coarsening that replaces a subgraph with a simpler
  element (or folds its effect into a neighbour) and **widens** the affected
  prior to stay honest about the approximation.

The `combine` rules are exactly today's combine rules, but their role is now
clear: **they define how a coarse element's effective params relate to the fine
ones it contains.** (They also tell you how to push a fitted effective value
*back down* over children by the combine weights, if ever needed — usually
unnecessary, since the fit answer lives at the cut.)

---

## φ, identifiability, and the cut

- **φ lives directly on cut-level elements** (e.g. `wall.R_eff`, `wall.C_eff`).
  No projection layer, no group-of-atoms indirection. This removes the class of
  bugs where the parameter the fit optimises differs from the parameter shown on
  the element (current bug #3, the `(N-1)/N` chain-R mismatch).
- **Identifiability *is* the act of choosing the cut.** "These south windows
  can't be separated" → cut *above* them so they are one element. The parallel-R
  merge becomes a graph rewrite on the small semantic graph (merge two 2-terminal
  components sharing an endpoint pair), not a heuristic that walks the atomic
  graph. The current `identifiability.py` chain-walking disappears.
- **Cut granularity (identification) is orthogonal to mesh granularity
  (dynamics).** You can fit a coarse "south-windows" group while still meshing a
  heavy wall finely for its 24 h lag.

---

## The two contracts

Each arrow has one explicit contract. These are where the current bugs become
*postcondition violations* — i.e. catchable by assertion / property test.

### Coarsening contract — (1)→(2), roll-up + uncertainty widening

For an element that summarises children via a `combine` rule:

- **Nominal roll-up** — the parent nominal is the combine of child nominals:
  - `series_sum`:        `R_parent = Σ R_child`
  - `parallel_inv_sum`:  `1/R_parent = Σ 1/R_child`  (parallel conductances)
  - `parallel_sum`:      `C_parent = Σ C_child`
  - `chain`:             `(R_parent, C_parent) = (Σ R_child, Σ C_child)`
  - `identity`:          `param_parent = param_child`  (single child)
- **Uncertainty widening** — when detail is *dropped* (not just merged), the
  parent `sigma` must be **≥** the rolled-up child sigma, widened to absorb the
  unmodeled physics (e.g. folding an unmodeled thermal bridge or a discarded
  small window into a neighbour widens that neighbour's prior). The toy model is
  honest about being a simplification by carrying fatter priors where detail was
  discarded.
- **Invertibility of the value map** — `combine` and its inverse (used to
  display / re-derive the effective nominal) must satisfy
  `reduce(expand(φ)) == φ`. Defining the rule as an `(expand, reduce)` pair with
  this property is what makes bug #3 impossible.

### Meshing contract — (2)→(3), conservation

For each cut-level element, the mesher emits type-B atoms (masses + conductances)
such that:

- **Resistance conserved:** `Σ R_atom (series path) == R_eff` of the element.
- **Capacitance conserved:** `Σ C_atom == C_eff` of the element.
- **Source gain conserved:** an n-terminal source fanned out to its targets has
  `Σ gain_atom == gain_eff`.

This contract makes current **bug #1** (a chain_n=1 wall silently dropping its
bulk `R_wall`, leaving only `Rse + Rsi`) a failed postcondition: an N=1 mesh that
places only surface resistances violates `Σ R_atom == R_eff` and must assert.

The mesher is the **type-A → type-B compiler** — the only component that knows
about atoms. It is the netlist→MNA step: the schematic (type A, multi-terminal
devices, behavioural RC-chain models) is what you edit and fit; the matrix
(type B, stamped Laplacian) is what you simulate. Nobody edits the matrix; nobody
simulates on the schematic.

---

## The atomic layer (3) and the fold-back

- **Type B, transient, never stored.** Regenerated by the mesher on every
  simulation/fit iteration. Matches the existing invariant: *the model is
  derived, never stored* — here pushed down to the atomic layer where it belongs.
- **Assembly = Laplacian stamping.** `Y[i,i] = Σ G_ij`, `Y[i,j] = -G_ij`. No
  resistance-node elimination, no chain-walking (resistances were never nodes).
- **Fold-back (atomic → effective observables) is a *selection*, not an
  inversion.** The fit perturbs effective params (which it holds), the mesher
  regenerates atoms, the solver runs, and only **observable** quantities map up
  (e.g. "room T = the room-air atom's T"; internal wall-lump temps are
  discarded). Because the fit operates on the effective layer, you never invert
  the mesh to recover effective params from atom states — you already hold them.

---

## Summary of the three layers

| | (1) Physical | (2) Toy model | (3) Atomic |
|---|---|---|---|
| Type | A (hierarchical hypergraph) | A (hierarchical hypergraph) | B (weighted Laplacian) |
| Relationship | leaf level | a **cut** through (1) | **meshed** from the cut |
| Node | room / boundary | room / boundary | mass (C to ground) |
| Component | wall / window / air-exch / source (n-terminal, owns R,C,gain) | same (possibly coarsened) | — (compiled away) |
| Edge | — | — | conductance (2-terminal, no state) |
| Internal state on between-elements? | yes (RC walls) | yes | no |
| Multi-terminal? | yes (shared sources) | yes | no |
| Stored? | yes (source of truth) | yes (the cut + coarsening choices) | no (regenerated) |
| Who reads it | user edits, geometry/materials | **the fit; identifiability; staleness** | the solver only |
| Arrow into it | — | coarsen (lossy, uncertainty-widening) | mesh (lossless, conservation) |

### What each layer fixes vs. the current code

- φ on effective components (not a projection over atoms) → removes the
  parameter-indirection mismatches (bug #3).
- Meshing conservation contract → makes the dropped-`R_wall` bug (#1) a failed
  postcondition.
- Identifiability as a cut/merge on the small effective graph → removes the
  triple-implemented resistance-chain walk (`assemble.py`, `view.py`,
  `identifiability.py`) and the heuristic `group_params`.
- One fit path on the effective layer → removes the legacy/φ-space dual paths
  (todo_1 #5/#6).

---

## Open item to pin down next

The **coarsening contract** above is stated for nominals and conservation, but
the **sigma-widening policy** (exactly how much to widen a prior when a detail is
dropped or folded into a neighbour) is not yet specified. That policy is the
analogue of the meshing conservation contract for *uncertainty*, and it is what
makes "the toy model is an honest simplification" testable. Specify it per
coarsening kind (merge vs. drop-and-fold) before implementing the (1)→(2) arrow.
