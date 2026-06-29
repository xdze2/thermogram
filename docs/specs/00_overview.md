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
is the **authoring vocabulary** — `elements → channels → modules` — and making that
mapping *visible* (the routing matrix, the topology graph). The specs here are organised
around that authoring core.

## Reading order

| #   | Spec                          | Scope                                                                 | Status   |
| --- | ----------------------------- | --------------------------------------------------------------------- | -------- |
| 00  | this file                     | overview, spec map, reading order                                     | —        |
| 10  | [`10_state.md`](10_state.md)  | **frontend data flow** — store as single source of truth, mutation→re-pull invariant, fixtures, multi-model | **built** |
| 20  | [`20_layout.md`](20_layout.md)| **UI layout** — 2-column single-page; routing matrix demoted to diagnostic | **built** |
| 30  | [`30_api.md`](30_api.md)      | the FastAPI ↔ Svelte contract (endpoints, JSON shapes, model management) | **frozen, built** |
| 40  | [`40_physics.md`](40_physics.md) | engine invariants as checkable statements (star topology, exactly-once ownership, channels, forms, band rule) | **built** (Steps 0–1) |

**Status legend.** *target* = the spec describes the intended design; the current code
does **not** yet satisfy it (a known-bug section says where it diverges). *frozen/built* =
the implementation conforms; treat the spec as describing existing behavior.

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
