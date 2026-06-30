# thnodes — Specs Overview

**This directory is the authoritative target-state specification for thnodes.**
When code and a spec here disagree, the spec wins — or the spec is wrong and must be
fixed *first*, before the code. The older design docs in `../background/` explain the
*why*; the specs here state the *what* and *how it must behave*.

---

## What thnodes is

`thnodes` is a single-room dynamic thermal building simulation + parameter-identification
tool. A user describes a room physically (walls, windows, floor, HVAC…); the app assembles
a minimal RC (resistor–capacitor) equivalent model and either **simulates** indoor
temperature `T_room` forward from weather/scenario inputs, or **fits** the thermal
parameters from sensor data by Bayesian inference. Local, single-user, single-session.

## The core bet

Everything rests on one design wager:

> A **star-topology** RC model — every module a two-terminal branch from `T_room` to a
> boundary — with **log-normal priors derived by spending conserved (element, channel)
> budgets**, yields a **posterior** that honestly covers the truth on collinear passive
> data. When the data cannot identify a parameter, the posterior says so (a wide marginal
> / a ridge), and the **identifiability lens predicts that in advance**.

The novel part is *not* the fit (Kalman + NUTS is standard inverse-problem machinery). It
is the **authoring vocabulary**: the user describes a room element-by-element, each element
declaring the **boundary (Signal)** it couples to, and the minimal RC model is **derived by
a hardcoded, building-physics-specific grouping rule** — one module per `(treatment,
boundary-signal)`. The specs here are organised around that authoring core.

> **Direction change (2026-06, exploration phase).** The earlier specs made the generic
> `elements → channels → modules` **routing matrix** the authoring surface — the user added
> modules and ticked element×channel cells, and the design "made that mapping visible." That
> re-imported the very generality v0.3 exists to avoid (see [`../README.md`](../../README.md)
> → *Design history*: the generic reduction is ill-posed). The current direction, specified
> in **[`15_signals_and_grouping.md`](15_signals_and_grouping.md)**, demotes channels to
> internal conservation bookkeeping and makes **per-element-type forms + the boundary Signal**
> the authoring vocabulary; modules become a **derived, read-only** projection. Specs `15`,
> `20`, `30`, `40` are being reconciled to this; where a spec still describes the routing
> matrix as the authoring surface, `15` wins.

## Reading order

| #   | Spec                          | Scope                                                                 | Status   |
| --- | ----------------------------- | --------------------------------------------------------------------- | -------- |
| 00  | this file                     | overview, spec map, reading order                                     | —        |
| 10  | [`10_state.md`](10_state.md)  | **frontend data flow** — store as single source of truth, mutation→re-pull invariant, fixtures, multi-model | **built** |
| 15  | [`15_signals_and_grouping.md`](15_signals_and_grouping.md) | **the authoring model** — first-class Signals, per-element boundaries, deterministic grouping into derived modules. *Supersedes the routing-matrix thesis.* | **target** |
| 20  | [`20_layout.md`](20_layout.md)| **UI layout** — 2-column single-page; element-form authoring, derived topology, routing matrix demoted to diagnostic | **partly built** (layout built; signal-grouping pending) |
| 30  | [`30_api.md`](30_api.md)      | the FastAPI ↔ Svelte contract (endpoints, JSON shapes, model management) | **in revision** (signal/treatment shapes pending) |
| 40  | [`40_physics.md`](40_physics.md) | engine invariants as checkable statements (star topology, exactly-once ownership, channels, forms, band rule, **grouping rule**) | **built** (Steps 0–1; I8 grouping pending) |

**Status legend.** *target* = the spec describes the intended design; the current code
does **not** yet satisfy it (a known-divergence section says where). *frozen/built* = the
implementation conforms; treat the spec as describing existing behavior. *in revision /
partly built* = mid-direction-change; read the spec's own status banner.

**Read `15` before `20`/`30`/`40`.** It is the design pivot the others are being reconciled
to; the rest still carry routing-matrix language in places, flagged where it conflicts.

## Background (the "why")

Authoritative for **rationale and physics derivation**, not for current behavior:

- [`../background/app_proposal.md`](../background/app_proposal.md) — the full engine
  design: motivation, the (element, channel) ownership model, the four flux forms, the
  band rule, prior derivation, the module catalogue. **Read this to understand *why* the
  specs say what they say.**
- [`../background/reading_note_bacher_madsen_2011.md`](../background/reading_note_bacher_madsen_2011.md)
  — the fit-method reference (Kalman prediction-error likelihood); what transfers from
  Bacher & Madsen (2011) and what does not, given this project's passive/collinear regime.

Sequencing and the "validate the engine before building UI" rationale live in
[`../roadmap.md`](../roadmap.md) and [`../TODO.md`](../TODO.md).
