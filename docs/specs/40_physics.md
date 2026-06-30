# 40 — Engine Invariants

**Status: BUILT (Steps 0–1), I8 pending.** The assembler, forward simulation, and
identifiability lens conform to invariants I1–I7 today. **I8 (the grouping rule) is a
TARGET** — it specifies how modules are *derived* from element boundaries under the
direction change in [`15_signals_and_grouping.md`](15_signals_and_grouping.md); the current
assembler still takes hand-routed modules instead. This spec states the invariants as
**checkable rules** the engine and its tests must uphold; the *derivation and rationale* live
in [`../background/app_proposal.md`](../background/app_proposal.md), which this file links
into rather than restates.

This is a thin spec on purpose: it exists so the assembler's contract is checkable without
reading the full proposal, and so the UI specs (`10`, `15`, `20`, `30`) have a stable
reference for the terms `channel`, `ownership`, `module`, `signal`, `band`.

> **Framing change (2026-06).** Channels and the (element, channel) ownership model (I2–I4)
> are **no longer the authoring vocabulary** — they are the assembler's *internal*
> conservation bookkeeping. The user authors *elements with boundaries*; modules are
> **derived** by the grouping rule (I8). So I2/I3 below are now properties the grouping rule
> **guarantees**, not constraints the user must satisfy by hand. See
> [`15_signals_and_grouping.md`](15_signals_and_grouping.md).

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

## I3 — Exactly-once ownership (a guarantee the grouping rule must uphold)

> **Per (element, channel): exactly one module claims it. Across channels: an element may be
> claimed by many modules.**

- A south window's `CONDUCTION` and `SOLAR_TRANSMISSION` are distinct cells → both fire,
  correct. (They route to different modules — by **signal**: `DirectLoss[T_ext]` and
  `SolarGain[G_sol_S]`. This is the canonical per-(element, channel) split, see I8.)
- Two modules claiming the same `CONDUCTION` cell is a **double-count**.
- A channel with a budget that no module claims is an **unclaimed_channel** problem.

Under the **grouping-rule model** (I8) these are no longer user errors to police — a correct
grouping rule produces exactly-once, complete ownership *by construction*. So I3 is now an
**internal consistency assertion on the rule's output**: a double-count or unclaimed channel
means the rule (or an element's budget computation) has an **engine bug**, surfaced as a
`problem` — never blamed on the user, who has no routing control to get wrong.

The assembler still checks it. In `strict=True` it raises on `double_count` /
`missing_room_mass` / `duplicate_state`; in `strict=False` (the API path) it collects every
violation into `problems[]` and still returns partial data — `/assembly` **never 500s**
(see [`30_api.md`](30_api.md)).

**Room auto-pairing.** `RoomMass` is mandatory (its absence is `missing_room_mass`). It owns
no channels of its own; instead the assembler **auto-routes the room's `IndoorMass` element**
(the element carrying the room's `STORAGE` budget) to it — the user never wires the room
manually. Consequently an `IndoorMass` element is now required alongside `RoomMass`; its
absence is also a `missing_room_mass` problem.
→ implementation: `assembler.py`; rationale: app_proposal §"The ownership rule".

## I4 — Modules spend budgets, they never re-invent them

> A module derives its prior by **spending its claimed channel budgets**, not by inventing
> physical quantities.

Canonical example: `HeavyWall` splits the element's single conserved `U·A` into
`H_out`/`H_in` by the ISO 6946 inner/outer surface-resistance ratio, around the element's
`C` (STORAGE). Energy and capacity are conserved by construction.

**The room obeys the same rule.** The room's mass is *not* a module heuristic — it is an
`IndoorMass` **element** that owns the room geometry (`a, b, c` dimensions + a `furniture`
level) and computes a `STORAGE` budget from it (air mass `ρ_air·V·c_air` plus a furniture
term). The `RoomMass` module is **pure topology**: it spends that `STORAGE` budget into the
`C_room` prior and does no physics of its own. No physical descriptor and no geometry lives
on a module — fields live on elements, period.
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

## I8 — The grouping rule (modules are derived, not routed) — **TARGET**

> Modules are **derived from elements** by a fixed, building-physics-specific rule:
> **one module per distinct `(treatment, boundary-signal)`**. The user never adds a module or
> routes an element; they author elements (each declaring a boundary) and, for a heavy wall,
> optionally pick its treatment.

- **Grouping key = `(treatment, signal)`.** Two elements that share a treatment *and* couple
  to the same boundary signal land in one module, which spends their **summed** channel
  budgets into its prior (I4). Two south windows → one `SolarGain[G_sol_S]`; a south + a west
  window → two modules. Two partitions to the kitchen → one `DirectLoss[T_kitchen]`; a
  partition to the hallway → a separate `DirectLoss[T_hallway]`.
- **The boundary signal is a first-class `Signal`** (role ∈ {exterior, ground, adjacent,
  solar, prescribed}), mostly auto-created from element boundaries. The set of signals the
  derived modules demand **is** the simulation input list.
- **Treatment is the only authoring knob**, and is forced except for the heavy-vs-light wall
  binary (the single choice the proposal sanctions, governed by I7). It lives on the
  **element**, not on a module.
- **Determinism, not search.** The rule is a pure function of (element type, fields,
  treatment, pinned signals) — it never optimises or reduces. This is the v0.3 escape from
  the ill-posed generic reduction (README → *Design history*) applied to authoring:
  extensibility is by **adding a rule**, not by re-opening a generic routing matrix.
- **Guarantees I2/I3 by construction.** A correct rule emits exactly-once, complete ownership;
  any double-count/unclaimed channel is an engine bug, not user error.

Full specification (Signal object, roles, per-element boundary fields, treatment menus, the
grouping algorithm, migration from routing) in
**[`15_signals_and_grouping.md`](15_signals_and_grouping.md)**.
→ status: TARGET — the current assembler takes hand-routed modules
(`add_module(..., elements=[...])`); the rule layer that derives them is not yet built.

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
