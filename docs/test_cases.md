# Modular RC — test cases  *(Stage 0 expressiveness pass)*

Six buildings, each decomposed into elements → `{channel: owning module}`. This is the
**expressiveness** pass: can a real building be *described* by the model at all? It uses the
generic physics from [`physics_model.md`](physics_model.md) (channels, modules, elements);
whether a given cell is computable from the current `priors.py` is **Stage 1's** scoping concern,
kept out of here.

The cases form a coverage matrix — each stresses a different degree of freedom:

| case | stresses | question it answers |
|---|---|---|
| **cave / cellar** | ground coupling, no solar | does STORAGE+ground work *without* solar? (Bacher's "constant room") |
| **caravan** | all-light, no STORAGE | does the model degrade to pure-resistive cleanly? |
| **regular house** | full mix | south-window dual-channel; heavy/light routing; the current default |
| **passive house** | extreme insulation, large solar | do the *ratios* stay physical at the extremes? |
| **Earthship** | ground berm + big south glazing | both solar channels + ground STORAGE at once (hardest) |
| **ITE vs ITI wall** | layer order of a heavy wall | does per-cell `RChain` beat a lumped node? (the load-bearing test) |

Conventions: per-element granularity (each heavy element keeps its own chain; aggregating into one
`C_wall` is a fit-time collapse). Cells = **owning module @ source**.

---

## Case 1 — Cave / cellar  *(ground coupling, no solar; Bacher's "constant room")*

| element | boundary | CONDUCTION | SOLAR | STORAGE |
|---|---|---|---|---|
| `wall_stone` | ground | `GroundLoss` | — | `HeavySlab`(RChain@T_ground) |
| `floor_slab` | ground | `GroundLoss` | — | `HeavySlab` |
| `partition` | adjacent | `AdjacentLoss` | — | — (light) |
| `ceiling_concrete` | adjacent | `AdjacentLoss` | — | `HeavyPartition`(RChain@T_adj) |

States: `T_room` + one chain per heavy element. The heavy ceiling-to-house is just `RChain@T_adj`
— the source-in-key change made it a free config, not a missing module.

---

## Case 2 — Caravan  *(all-light; degrades to pure-resistive)*

| element | boundary | CONDUCTION | SOLAR | STORAGE |
|---|---|---|---|---|
| `wall_panel` ×4 | exterior | `DirectLoss` | `SolarGain`(sol-air) | — |
| `roof_panel` | exterior | `DirectLoss` | `SolarGain`(sol-air) | — |
| `floor_panel` | exterior | `DirectLoss` | — | — |
| `window` | exterior | `DirectLoss` | `SolarGain`(transmitted) | — |
| (ventilation) | exterior | `DirectLoss` (ACH) | — | — |

Modules: `RoomMass` + `DirectLoss` + `SolarGain`. State: `T_room` only. ✓ no heavy node.

---

## Case 3 — Regular house  *(full mix, current default, south-window dual-channel)*

| element | boundary | CONDUCTION | SOLAR | STORAGE |
|---|---|---|---|---|
| `wall_brick` ×4 (heavy) | exterior | `HeavyWall`(RChain@T_ext) | `HeavyWall` sol-air | `HeavyWall` |
| `roof` (light) | exterior | `DirectLoss` | `SolarGain`(sol-air) | — |
| `floor` (heavy) | ground | `GroundLoss` | — | `HeavySlab` |
| `win_S` | exterior | `DirectLoss` | `SolarGain`(transmitted) | — |
| `win_N` | exterior | `DirectLoss` | `SolarGain`(transmitted) | — |
| (ventilation) | exterior | `DirectLoss` (ACH) | — | — |

✓ South-window dual-channel (`CONDUCTION`→`DirectLoss`, `SOLAR`→`SolarGain`, both fire).
✓ Heavy/light routing (brick `CONDUCTION` owned by `HeavyWall` only). A 40 cm brick wall can run
`RChain` with `N`=5–10. Aggregated collapse (`N=1`, 4 walls → one chain) recovers 2R2C.

---

## Case 4 — Passive house  *(extreme insulation, large solar; ratio/extreme test)*

Same channel shape as the house, very low `U·A`/ACH. Heavy mass **inboard** of insulation
(well-coupled) — the opposite of the house roof tiles. No new channel; confirms the `RChain`
`H_out/H_in` split must encode which side of the insulation the mass sits. Its job is Stage 3
dynamics, not Stage 0 expressiveness.

---

## Case 5 — Earthship  *(ground berm + big south glazing; hardest)*

| element | boundary | CONDUCTION | SOLAR | STORAGE |
|---|---|---|---|---|
| `berm_wall` | ground | `GroundLoss` | — | `HeavySlab`(berm) |
| `south_glazing` | exterior | `DirectLoss` | `SolarGain`(transmitted) | — |
| `south_mass` | interior | `HeavyWall`(interior) | `SolarGain`(**interior-absorbed**) → mass node | `HeavyWall` |
| `roof` (green) | ground/exterior | `GroundLoss`/`DirectLoss` | `SolarGain`(sol-air) | — |
| `floor` | ground | `GroundLoss` | — | `HeavySlab` |
| (ventilation) | exterior | `DirectLoss` (ACH) | — | — |

States: `T_room` + chains for berm / floor / south_mass. Stresses: (1) transmitted solar lands on
`south_mass`'s outer node, not `T_room` — `SolarGain` must target a chain node (**Hole #1**); (2)
berm = `CONDUCTION@T_ground` + `STORAGE` in one `RChain` ✓.

---

## Case 6 — Renovated old wall: ITE vs ITI  *(the `RChain` layer-order stress test)*

Not a building typology but a **paired test**: one heavy wall (40 cm brick, south), **same
materials and same `U·A`/`C_heavy` budgets**, in two layer orders. The only difference is *where the
insulation sits relative to the mass* — and the dynamics must come out opposite.

| variant | layer stack (room → ext) | mass position | expected room-side inertia |
|---|---|---|---|
| **ITE** (external insul.) | plaster · **brick 40cm** · insulation · render | inboard of insulation | **high** — wall buffers room, slow cooldown |
| **ITI** (internal insul.) | plasterboard · insulation · **brick 40cm** · render | outboard of insulation | **low** — mass decoupled from room, ~wasted |

Both variants: same element, same channels —

| element | boundary | CONDUCTION | SOLAR | STORAGE |
|---|---|---|---|---|
| `wall_brick_40` | exterior | `HeavyWall`(RChain@T_ext) | `HeavyWall` sol-air | `HeavyWall` |

**The point.** A lumped `N=1` `C_wall` **cannot distinguish ITE from ITI** — identical total `C` and
`U`. Only the `N`-node `RChain` with per-cell `R_i, C_i` sliced *in layer order* captures it: in ITE
the high-`C` cells sit at the room end of the chain (small resistance to `T_room`); in ITI the big
insulation `R` sits between the mass and the room, so `T_room` sees mostly the light plasterboard.
**This is the headline demonstration of Hole #3** and the cheapest falsification of the whole
`RChain` story: if it can't get ITE τ ≫ ITI τ from the same materials, the discretization buys
nothing. → Stage 3 sanity assertion.

**Explicitly out of scope for the RC model** (real in renovation, not carried here):
- **Thermal bridges** (ITI's weak point — slabs/party walls pierce the insulation): a *correction to
  `U·A`* (lumped Ψ·L, ISO 14683), addable to the `CONDUCTION` budget; prior from a separate
  catalogue. **Deferred, not modelled now.**
- **Humidity / interstitial condensation** (ITI's real danger — dew point inside the brick): a
  moisture-transport problem, **orthogonal to the thermal RC model. Out of scope.**

---

## Verification summary

- **Exactly-once invariant:** ✓ all six cases — no `(element, channel)` cell has two owners. The
  south window (Case 3) and berm wall (Case 5) confirm the rule separates legitimate distinct-paths
  from illegal double-counting.
- **Holes surfaced** (full detail in [`physics_model.md`](physics_model.md#open-holes--decisions-none-block-for-stage-2-design)):
  (1) direct-gain onto interior mass (Earthship); (2) heavy/light routing key (caravan); (3) heavy
  layer position vs insulation (ITE/ITI).

**Stage 1 scope (computable from current physics):** caravan, regular house, passive house. Cave
and Earthship are **Stage-0-only** until ground/adjacent/interior-solar physics lands (Deferred in
the roadmap).
