# 40 — Engine Invariants

**Status: BUILT (Steps 0–1).** The assembler, forward simulation, and identifiability lens
conform to these invariants today. This spec states them as **checkable rules** the engine
and its tests must uphold; the *derivation and rationale* live in
[`../background/app_proposal.md`](../background/app_proposal.md), which this file links into
rather than restates.

This is a thin spec on purpose: it exists so the assembler's contract is checkable without
reading the full proposal, and so the UI specs (`10`, `20`, `30`) have a stable reference for
the terms `channel`, `ownership`, `module`, `band`.

---

## I1 — Star topology

> Every `TopologyModule` is a **two-terminal device**: one terminal is always `T_room`, the
> other is a **boundary signal** (`T_ext`, `T_ground`, `T_adj`, `G_sol`, `Q_hvac`, …). A
> module may own **private** hidden states, but those nodes are private — **no other module
> connects to them.**

The RC graph is a star centred on `T_room`, never a free network. Consequence: assembly is
just *collecting branches*; there is no shared-internal-node connectivity to reason about.
Shared internal nodes are exactly the non-identifiable degrees of freedom this design
excludes by construction.
→ rationale: app_proposal §"Star topology", §"Solar is a reusable boundary helper".

## I2 — The (element, channel) ownership model

> The unit of ownership is the **(element, channel) pair**, not the element.

Each element exposes conserved **channel budgets**, computed once, model-agnostic:

| Channel              | Budget        | Offered by                                  |
| -------------------- | ------------- | ------------------------------------------- |
| `CONDUCTION`         | `U·A`         | opaque walls, windows, roof, floor          |
| `SOLAR_TRANSMISSION` | `SHGC·A`      | glazing                                     |
| `SOLAR_OPAQUE`       | `α·A`         | all opaque exterior elements (light + heavy)|
| `STORAGE`            | `C` of heavy layers (ρ > 500) | walls/roof/floor with heavy layers |

(Enum + `Budget` shape in `channels.py`; mirrored in the API as
[`30_api.md`](30_api.md) `Element.budgets`.)
→ rationale: app_proposal §"Ownership: the (element, channel) model".

## I3 — Exactly-once ownership (hard error)

> **Per (element, channel): exactly one module may claim it. Across channels: an element may
> be claimed by many modules.**

- A south window's `CONDUCTION` and `SOLAR_TRANSMISSION` are distinct cells → both fire,
  correct.
- Two modules claiming the same `CONDUCTION` cell is a **double-count** → a hard assembly
  error, never a silent bug in the fit.
- A channel with a budget that no module claims is an **unclaimed_channel** problem.

The assembler enforces this. In `strict=True` it raises on `double_count` /
`missing_room_mass` / `duplicate_state`; in `strict=False` (the API path) it collects every
violation into `problems[]` and still returns partial data — `/assembly` **never 500s**
(see [`30_api.md`](30_api.md)).
→ implementation: `assembler.py`; rationale: app_proposal §"The ownership rule".

## I4 — Modules spend budgets, they never re-invent them

> A module derives its prior by **spending its claimed channel budgets**, not by inventing
> physical quantities.

Canonical example: `HeavyWall` splits the element's single conserved `U·A` into
`H_out`/`H_in` by the ISO 6946 inner/outer surface-resistance ratio, around the element's
`C` (STORAGE). Energy and capacity are conserved by construction.
→ rationale: app_proposal §"Prior derivation", §"The ownership rule".

## I5 — Four canonical flux forms

> Every physical term reduces to one of four forms. The discriminator is **does it have
> memory?**

| Form                 | Flux into `T_room`          | Params              | Reads channels        | Private state |
| -------------------- | --------------------------- | ------------------- | --------------------- | ------------- |
| `Conductance`        | `H·(T_bnd − T_room)`        | H                   | CONDUCTION            | —             |
| `SolarGain`          | `α·A·G` into target node    | α·A                 | SOLAR_TRANSMISSION    | —             |
| `DelayedConductance` | `H_in·(T_node − T_room)`    | H_out, H_in, C_node | CONDUCTION + STORAGE  | T_node        |
| `SourceFlux`         | `Q(t)`                      | —                   | — (raw signal)        | —             |

Memoryless → `Conductance` / `SolarGain` / `SourceFlux`; with thermal mass →
`DelayedConductance`. Sol-air is **not** a fifth form — it is a boundary the owning module
constructs internally.
→ implementation: `forms.py`, `modules.py`; rationale: app_proposal §"Four canonical flux
forms", §"Module catalogue".

## I6 — Priors are log-normal; sampling is in `log θ`

> All physical parameters are strictly positive and span orders of magnitude, so priors are
> **log-normal** (Gaussian in `log θ`), expressed as `(mu_log, sigma_log)`.

"±60%" is the multiplicative factor `σ_log = ln(1.6)`. This is what `derive_priors` returns
and what `/assembly` surfaces per parameter.
→ rationale: app_proposal §"Prior derivation".

## I7 — The band rule (a private state needs a new time-constant band)

> A module may add a private hidden state **only if it introduces a new time-constant band**
> not already present. Two states in the same band are not separately identifiable from a
> single indoor sensor and must be lumped.

This is the physically-grounded identifiability criterion (replacing any "N free parameters"
heuristic). It governs the heavy/light routing choice and is what the **identifiability
lens** checks at prior-mean poles before any fit.

**Scope:** the band rule and the whole identifiability limit apply to **③ the fit only**.
The **simulation toy (①②) has no identifiability limit** — forward integration needs no
inversion, so it can stack as many modules/states as the physics warrants.
→ implementation: `identifiability.py`; rationale: app_proposal §"The C_room splitting
problem", §"Identifiability".

---

## What is *not* specified here

- The **fit layer** (Kalman prediction-error likelihood, NUTS sampling, JAX/NumPyro) — Steps
  2–3, not yet built. When it lands it gets its own spec (`50_fit.md`). Until then, see
  app_proposal §"Estimation" and
  [`../background/reading_note_bacher_madsen_2011.md`](../background/reading_note_bacher_madsen_2011.md).
- The full **module catalogue** (`GroundLoss`, `AdjacentLoss`, `IndoorMass`, `HeavySlab`, …)
  beyond the Step-0 minimum — see app_proposal §"Module catalogue".
- **Topology rendering** internals (schemdraw → SVG) — an implementation detail of the
  `topology.svg` endpoint in [`30_api.md`](30_api.md).
