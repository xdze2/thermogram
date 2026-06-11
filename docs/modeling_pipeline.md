# Modeling pipeline

How a noisy, partial physical description of a house becomes a fittable model
— and how the fit feeds back to refine the description.

This is a **design document**. The current code implements early pieces of it
(notably the layer-1 element list and a degenerate version of the atomic/lumped
split); the goal here is to spell out the target architecture, the data
objects, and the operations that connect them.

For the high-level project overview see [project_description.md](project_description.md).

---

## Premise

The user describes a house with limited and uncertain information: some
geometry guessed, some materials approximated, some elements forgotten. The
measurements (indoor temperature, heating power, weather) are partial.

We do **not** want a rigid expand-reduce-fit pipeline. We want a loop:

> Start with the coarsest model that can possibly explain the data. Fit it.
> Look at the residuals and at how each parameter's posterior compares to
> the user's prior. Decide whether to refine the model, whether to coarsen
> it, and which user inputs the fit is telling us to revise. Iterate.

The expert (or an LLM agent) drives that loop. The code provides the kernels
the loop calls.

---

## Three layers of representation

```
┌────────────────────────────────────────────────────────────────────┐
│ DOMAIN MODEL  — what the user / agent reasons in                   │
│                                                                     │
│   envelope: opaque, glazing, infiltration, ground                  │
│   internal: air, mass, air↔mass coupling                           │
│   inter-zone: partition, opening                                   │
│   sources: heating, solar, occupancy                               │
│   boundaries: T_outdoor, T_ground, T_neighbor                      │
│                                                                     │
│   Domain elements describe ROLES, not quantities. They are not     │
│   directly fittable — they are realized by lumped elements.        │
└────────────────────────────────────────────────────────────────────┘
                              │
                              │  a View picks lumped elements
                              │  that realize the domain
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ LUMPED MODEL  — the φ-space, what the fit operates on              │
│                                                                     │
│   Req            (lossless aggregation of series/parallel R)       │
│   Ceq            (lossless aggregation of parallel C)              │
│   RC_chain(n)    (parametric — n controls dynamics fidelity)       │
│   T_boundary     (driven node, atom exposed directly)              │
│   Q_source       (injected power, atom exposed directly)           │
│                                                                     │
│   Each lumped element carries:                                      │
│     - a Belief (prior, composed from atomic Beliefs)                │
│     - a mode: free / fixed / tied                                   │
│     - an optional Modulator (gain(t), schedule(t))                  │
│     - provenance: which atoms it covers, which domain it realizes  │
└────────────────────────────────────────────────────────────────────┘
                              │
                              │  lumped elements expand to atoms via combine rules
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ ATOMIC MODEL  — what the solver assembles                          │
│                                                                     │
│   R, C, T(t), Q(t)                                                  │
│   Pure math. No physics meaning, no priors.                        │
│   Atoms may carry an optional modulator(t) attached at the         │
│   lumped level (e.g. shutter gain on a window R).                   │
└────────────────────────────────────────────────────────────────────┘
```

The crucial points:

- **Atoms** are what the solver sees. Building A and B matrices, simulating,
  computing residuals — all at the atomic model level.
- **Lumped elements** are what the fit sees. The φ-vector, priors, posteriors,
  correlations — all at the lumped model level. This is the identifiability boundary.
- **Domain elements** are what the user and the agent talk in terms of.
  "Refine the south wall" is a domain-level statement; it produces a
  lumped-model change which the fit then sees.

A **View** (defined below) is a choice of lumped elements that, together, realize the
domain model at a chosen abstraction level. The same domain description can
be viewed many ways.

---

## Beliefs: uncertainty is first-class

Every declared quantity in the physical description is a `Belief`, not a
number. A Belief carries a value, a confidence, and provenance.

```python
@dataclass
class Belief:
    value: float
    confidence: Literal["known", "measured", "estimated", "guessed"]
    sigma_log: float            # numeric backing; "known" ⇒ 0
    source: str                 # "user" | "study:<id>" | "material_db" | ...
    updated_at: datetime | None
```

- `known` (e.g. measured wall area) ⇒ tight prior, won't move.
- `measured` ⇒ moderate prior.
- `estimated` ⇒ wide prior.
- `guessed` (e.g. "old brick, probably") ⇒ very wide prior, easily updated.

Priors at the lumped layer are **composed** from these Beliefs at view-build
time. The user never writes a prior on `R_envelope` directly — they declare
beliefs about thickness, λ, area, and the composition rules produce the
aggregate prior with appropriately propagated uncertainty.

---

## Data objects

### Layer 1 — Elements (with beliefs)

```python
@dataclass
class Element:
    id: str
    kind: Literal["wall", "roof", "window", "ground", "infiltration",
                  "shutter", "outdoor", "room", "partition", "heater", ...]
    geometry: dict[str, Belief]      # area, thickness per layer, volume, ...
    material: str | None
    between: tuple[ElementId, ElementId] | None
    beliefs: dict[str, Belief]       # any other declared quantity
    modulator_ref: str | None        # link to a Modulator (e.g. shutter schedule)
    notes: str | None
```

The house file is a list of Elements plus a material library and a
modulators list. This is the source of truth.

### Atom

```python
@dataclass
class Atom:
    id: str
    kind: Literal["R", "C", "T_boundary", "Q_source"]
    value: Belief                    # base value, before modulation
    modulator: Modulator | None      # optional time-varying multiplier
    source: ElementId                # which Element produced this atom

@dataclass
class Modulator:
    kind: Literal["constant", "schedule", "control_law", "signal"]
    params: dict                     # gain value, schedule table, signal ref, ...
```

Atoms are derived from Elements by a deterministic per-element function
(`build_atoms`). One wall with N layers produces 2 surface R atoms + N layer
R atoms + N internal C atoms (or 0 C atoms if `no_mass`).

### Lumped element — the φ-space

```python
@dataclass
class LumpedElement:
    id: str
    kind: Literal["Req", "Ceq", "RC_chain", "T_boundary", "Q_source"]
    # kind-specific structure:
    n: int | None                    # only for RC_chain (chain length)
    # Provenance:
    atoms: list[AtomId]              # which atoms this lump aggregates
    combine: CombineRule             # how atoms compose into the lump value(s)
    realizes: DomainRef              # which domain element this realizes
    # Fit-facing:
    prior: Belief                    # composed from atom value Beliefs
    mode: Literal["free", "fixed", "tied"]
    tied_to: LumpedElementId | None
    modulator: Modulator | None      # inherited from atoms or from domain
    # Filled after fit:
    posterior: Belief | None

CombineRule = Literal[
    "series_sum",        # Req from series R atoms
    "parallel_sum",      # Ceq from parallel C atoms
    "parallel_inv_sum",  # Req from parallel R atoms
    "chain",             # RC_chain — distributes R_total, C_total across n lumps
    "identity",          # T or Q exposed directly
]
```

The `combine` rule answers: given the lumped element's posterior value(s), what are
the atom values? For `RC_chain(n)`, the rule takes two parameters (R_total,
C_total) and produces 2n+1 atoms (n+1 R's alternating with n C's).

Note that `RC_chain(n)` is **one lumped element with two free quantities** (R_total
and C_total). Increasing n changes dynamics fidelity without adding fit
parameters.

### Domain elements

```python
@dataclass
class DomainElement:
    id: str
    role: DomainRole
    zone: str | None                 # which room/zone, if applicable
    composed_of: list[ElementId]     # which layer-1 elements participate
```

```python
DomainRole = Literal[
    # Envelope (zone ↔ outside)
    "opaque_path", "glazing_path", "infiltration_path", "ground_path",
    # Internal (within zone)
    "air_node", "mass_node", "air_mass_coupling",
    # Inter-zone
    "partition", "opening",
    # Sources / sinks
    "heating", "solar_gain", "internal_gain",
    # Boundaries (driven)
    "T_outdoor", "T_ground", "T_neighbor",
]
```

Domain elements are derived from the house. The user does not write them
directly — they emerge from element kinds and `between` relations. They are
the level the agent reasons in.

### View — the φ-space at a chosen abstraction

```python
@dataclass
class View:
    id: str
    scope: list[ElementId]                    # which elements participate
    lumped: list[LumpedElement]               # the φ-space — what fit() sees
    # Derived indexes:
    by_domain: dict[DomainRef, list[LumpedElementId]]
    by_atom:   dict[AtomId, LumpedElementId]
```

A View is a choice of lumped elements that **covers every active atom exactly once**.
Coarse view: few lumped elements, each covering many atoms (e.g. one `Req` for the
whole envelope). Fine view: many lumped elements, each covering few atoms (one
`Req` + `Ceq` per wall, possibly an `RC_chain` for heavy walls).

The View is what gets persisted with a Study. The atoms and the underlying
Elements are not persisted in the View — they are recomputed.

### Study

```python
@dataclass
class Study:
    id: str
    house_ref: str
    view: View                          # lumped model at chosen abstraction
    window: TimeRange
    inputs: dict[str, SignalRef]        # T_outdoor(t), Q_heating(t), ...
    observations: dict[str, SignalRef]  # T_indoor(t), ...
    fit_config: FitConfig
    result: FitResult | None
    insights: list[Insight]             # what each fit told us about Elements
```

### Insight — the loop back

```python
@dataclass
class Insight:
    study_id: str
    timestamp: datetime
    updates: list[BeliefUpdate]

@dataclass
class BeliefUpdate:
    element_id: ElementId
    quantity: str                    # "thickness", "lambda", "R_total", ...
    prior: Belief
    posterior: Belief
    via: LumpedElementId             # which φ produced this
    accepted: bool | None            # None = pending user review
```

An Insight is a *proposal*. Each `BeliefUpdate` is reviewed (by user or
agent) and accepted/rejected. Accepted updates rewrite the Element's
beliefs and carry the study id as `source`.

---

## Operations

Four deterministic kernels and two agent-level operations.

### Deterministic kernels

```python
def build_atoms(element: Element, materials: MaterialLibrary) -> list[Atom]:
    """One element → its atoms. Pure, per-element, no graph context."""

def build_domain(house: House) -> list[DomainElement]:
    """Element list + 'between' relations → domain element list.
    Deterministic; groups elements by their physical role."""

def fit(view: View, study: Study) -> FitResult:
    """φ-space fit. Reads lumped element priors, runs solver via atom expansion,
    returns posteriors on the free lumped elements plus residuals and diagnostics
    (AIC, correlation matrix, Jacobian)."""

def attribute(result: FitResult, view: View) -> Insight:
    """Posterior on lumped elements → proposed BeliefUpdates on Elements.

    For each lumped element, distribute the posterior across its atoms (via the
    combine rule's inverse) and onward across the atoms' source-element
    beliefs, weighted by each Belief's prior confidence ('known' Beliefs
    absorb nothing; 'guessed' Beliefs absorb most of the update)."""
```

### Agent-level operations

```python
def propose_view(domain: list[DomainElement], depth: ViewDepth) -> View:
    """Pick lumped elements to realize the domain at a chosen coarseness.
    depth='coarse' → one Req per zone envelope, one Ceq per zone.
    depth='fine'   → one Req+Ceq per element, RC_chain on heavy walls.
    Intermediate depths possible."""

def transform_view(view: View, op: ViewOp) -> View:
    """Apply one structural change. ViewOps:
      - refine(lump_id):   split one lumped element into several finer ones
      - coarsen(group):    merge several lumped elements into one
      - resolve(lump_id):  for RC_chain, increase n (more dynamics fidelity,
                           no new φ's)
      - fix(lump_id):      change mode to fixed at prior value
      - free(lump_id):     change mode to free
      - tie(a, b):         tie two lumped elements to share one φ
    """
```

`refine` and `coarsen` change the φ count. `resolve` is unique to
`RC_chain`: it changes dynamics fidelity without changing the φ count.
`fix`/`free`/`tie` change which φ's are active.

---

## The loop

```
   ┌─────────────────────────────────────────────────────────┐
   │ House (Elements + Beliefs)                              │◄────────┐
   └────────────────────────┬────────────────────────────────┘         │
                            │ build_atoms, build_domain                 │
                            ▼                                          │
   ┌─────────────────────────────────────────────────────────┐         │
   │ Atoms  +  Domain elements                                │         │
   └────────────────────────┬────────────────────────────────┘         │
                            │ propose_view(depth=coarse)                │
                            ▼                                          │
   ┌─────────────────────────────────────────────────────────┐         │
   │ View (lumped elements, priors, mode)                     │◄──┐    │
   └────────────────────────┬────────────────────────────────┘   │    │
                            │ fit                                 │    │
                            ▼                                     │    │
   ┌─────────────────────────────────────────────────────────┐   │    │
   │ FitResult: posterior on lumped elements, residuals, diag. │   │    │
   └────────────────────────┬────────────────────────────────┘   │    │
                            │                                     │    │
              ┌─────────────┴─────────────┐                       │    │
              ▼                           ▼                       │    │
   ┌─────────────────────┐   ┌─────────────────────────┐         │    │
   │ attribute → Insight │   │ inspect residuals + φ   │         │    │
   │ (proposed Belief    │   │ correlations → decide:   │         │    │
   │  updates on house)  │   │ refine? coarsen?         │         │    │
   └──────────┬──────────┘   │ resolve? tie?            │         │    │
              │              └─────────────┬───────────┘         │    │
              │ user / agent               │ transform_view       │    │
              │ accepts                    └──────────────────────┘    │
              │                                                        │
              └────────────────────────────────────────────────────────┘
                          (Beliefs updated on Elements)
```

Two arrows out of every FitResult:

- **Down** to the Elements, via `attribute`: a posterior on `Req_envelope`
  becomes proposed updates to the underlying λ, thickness, area Beliefs,
  weighted by their confidence.
- **Up** to the View, via `transform_view`: the residual structure and
  posterior correlations tell us how to change the abstraction level.

Both arrows can be taken at every iteration. The agent's job is to decide
which, and when to stop.

---

## What the agent does

The agent is the loop driver. It does not do physics. It calls
deterministic tools and decides what to do next based on their output.

Tool surface:

```python
build_atoms(element)            # rarely called directly; usually batch
build_domain(house)
propose_view(domain, depth)
fit(view, study)
attribute(fit_result, view)
transform_view(view, op)
apply_insight(house, insight, accepted_indices)
flag_input(element_id, quantity, reason)   # for user review, no auto-apply
```

The agent's decisions are recorded as a **trace** attached to the study,
along with each tool call's result. The trace is replayable: re-running an
agent on the same house+study should produce the same final view (modulo
LLM nondeterminism, which the trace exposes).

What the agent *should* do, in spirit:

1. Start with `propose_view(domain, depth='coarse')`. Fit.
2. Look at residuals. If they fit cleanly, attribute and stop.
3. Look at φ correlations. If two φ's are highly correlated, propose `tie`
   or `coarsen`.
4. Look at posterior vs. prior. If a φ is pegged at a bound or has very
   wide posterior, propose `fix` or `coarsen` (uninformative).
5. Look at residual *structure* (lags, periodicities). If structure remains,
   propose `refine` or `resolve` in the relevant subtree.
6. Iterate until residuals are unstructured and every φ is identifiable.
7. Call `attribute` to produce proposed Belief updates. Present to user.

The agent narrates each decision. Every quantitative claim it makes is
backed by a tool result, citable in the trace.

---

## What gets persisted

| Object          | Where                       | Recomputed when                |
|---|---|---|
| Elements + Beliefs | `data/houses/<name>.json` | user-edited, insight-applied   |
| MaterialLibrary | `data/materials.json`       | rarely                          |
| Atoms           | not stored                   | every fit                       |
| Domain elements | not stored                   | every fit                       |
| View            | embedded in Study            | edited via transform_view       |
| FitResult       | embedded in Study            | each fit                        |
| Insight         | embedded in Study            | after each attribute            |
| Agent trace     | embedded in Study            | as the agent runs               |

Nothing derived (atoms, domain, A/B matrices) is persisted. The house file
+ study (with its view, fit result, insights, and trace) is fully
determining.

---

## Module layout

```
solver/
  beliefs.py          # Belief, composition, prior propagation
  elements.py         # Element schema, house loader
  atoms.py            # build_atoms — per-element atom expansion (→ atomic_model)
  domain.py           # build_domain — element list → domain model
  lumps.py            # LumpedElement, combine rules, RC_chain math
  view.py             # View, propose_view, transform_view
  assemble.py         # atomic_model → AssembledSystem (A, B matrices)
  simulate.py         # solver — simulate_ivp, simulate_zoh
  fit.py              # fit(view, study) — wraps scipy + prior residuals
  attribute.py        # attribute — posterior → BeliefUpdates
agent/
  tools.py            # deterministic tool wrappers exposed to the LLM
  loop.py             # the agent loop, trace recording
```

Four new modules (`beliefs.py`, `atoms.py`, `domain.py`, `lumps.py`,
`view.py`, `attribute.py`) and an `agent/` subpackage. The existing
`physics.py` is replaced by the explicit atom/lumped/view split.

---

## UI consequences

Three panes, mapped to the three layers:

- **House editor** (domain + elements): the user edits Elements and their
  Beliefs. Confidence is set via a four-way control per declared quantity.
- **View editor** (lumped): the φ-space table — name, kind, prior,
  posterior, mode, modulator. Refine/coarsen/resolve/tie buttons on each
  row. Underneath, the reduced graph drawn with edges labeled by their
  controlling lumped element.
- **Study runner** (fit + insight): launch fits, inspect residuals, review
  proposed BeliefUpdates, accept/reject each one, see the agent trace.

The atoms layer has no UI — it's an implementation detail of the solver.

---

## Open questions

1. **Chain depth `n` per study, or per element?** Likely per study: a
   daily-resolution study needs n=1; a 15-minute study may need n=5. The
   View carries `n` per `RC_chain` lumped element.
2. **Attribution weighting.** How exactly does a posterior on `R_envelope`
   distribute across its atoms' source beliefs? Naive: by relative prior
   variance. Better: by partial-derivative-weighted variance. This is the
   genuinely subtle step and probably needs the agent's judgment as well
   as a default rule.
3. **Cross-study learning.** A posterior on brick λ from one study should
   inform the next study's prior on brick λ in another room. The
   `Belief.source` field supports this; the policy for when to auto-merge
   vs. require user confirmation is undecided.
4. **Modulators on aggregated lumped elements.** A `Req` covering five wall layers
   that all share a shutter modulator inherits cleanly. A `Req` covering
   mixed-modulator atoms (some shuttered, some not) doesn't — likely the
   view should refuse to form such a lumped element, forcing the user/agent to
   keep them split.
