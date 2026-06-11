# thermogram — todo

---

## Data model

### House file (`houses/<name>.json`)

One file per house. The RC model is derived deterministically from elements on
load — not stored. Studies are embedded in the house file.

```json
{
  "name": "my_house",
  "elements": [ ... ],
  "studies": [
    {
      "id": "<uuid4>",
      "label": "Winter 2024",
      "type": "run",
      "date_range": ["2024-01-01", "2024-02-28"],
      "inputs": {
        "solar_signal": "...",
        "obs_signal": "..."
      },
      "result": {
        "settings": { ... },
        "model_hash": "a3f9bc...",
        "output_file": "my_house_<study_id>_run_20240115T143022.parquet",
        "result_params": { ... }
      }
    }
  ]
}
```

Each study is either `"type": "run"` (forward simulation) or `"type": "fit"` (parameter estimation) — not both. `result_params` is only populated for fit results.

### RC model (derived, not stored)

`expand(elements) → rc_model` — pure function, called on load and after any
element edit. No selection mechanism: all elements are always used.

### Model hash

SHA-256 of the canonical JSON serialization of `elements` (keys sorted,
no whitespace), first 12 hex chars. Stored on each run/fit result. On load,
recompute and compare — flag study as stale if they differ.

```python
def model_hash(elements):
    canonical = json.dumps(elements, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]
```

### Parquet files

Stored alongside house files. Named automatically:
`<house_name>_<study_id>_<type>_<timestamp>.parquet`
where `<type>` is `run` or `fit`. Referenced by filename in the study JSON.

---

## Milestones

### ~~M1 — House view: flat list~~ ✓ done
### ~~M1b — House view: grid layout + icon toolbar + split view~~ ✓ done
### ~~M1c — UUID + label rename~~ ✓ done
### ~~M2 — Element signals~~ ✓ done
### ~~M3 — `expand()` + study spawning~~ ✓ done

### ~~M4 — New data model migration~~ ✓ done

Migrate from the current study-centric layout to the house-centric model
described above.

1. **Backend**: `houses/` directory, `GET /houses`, `GET /houses/{name}`,
   `PUT /houses/{name}`. Studies embedded in house JSON.
2. **`expand(elements)`** — drop the `selection` argument; always expand all
   elements.
3. **Model hash** — compute on every save; store on run/fit results; expose
   stale flag on load.
4. **Parquet naming** — `<house>_<study_id>_<type>_<timestamp>.parquet`.
5. **UI** — house picker / list on home screen; study list inside house view.

### M5 — Results projected back on house

1. `GET /houses/{name}/studies/{id}/results_by_element` — projects run output
   through expansion map, returns `{ element_id: { Q_mean, Q_peak, T_mean? } }`.
2. House rows show `Q_mean` / `Q_peak` badges after a run, color-tinted by
   magnitude.
3. Click a row → filter study charts to that element's traces.

### ~~M6 — Working Fit~~ ✓ done

1. ~~Fit runs correctly end-to-end (NLS + optional MCMC).~~ ✓
2. ~~Fit result saved: `result_params` in house JSON; model hash + timestamp stored.~~ ✓
3. ~~Model hash stored on fit result; stale flag shown if elements changed.~~ ✓
4. ~~Post-fit forward simulation with fitted params + charts (temperatures, residuals, input power).~~ ✓
5. ~~`param_overrides` on `/simulate/run` — patches RC model with fitted values before solve.~~ ✓
6. ~~`y0_uniform` propagated to fit (`/fit/run`) and post-fit simulation (`/simulate/run`).~~ ✓
7. ~~Human-readable parameter names + units in FitPanel tables.~~ ✓
8. Post-fit `λ ± σ` badges per layer on house rows, color-coded by posterior shift vs prior.
9. **Promote to priors** — write `result_params` back as tightened priors on elements.

### M7 — Fit UI polish

#### M7.1 — Initial values for fit parameters

Currently `nominal` values shown in FitPanel come from the RC model node fields
(the physical defaults set at expand time). These are often poor starting points,
especially for `C` nodes (thermal mass), causing slow convergence or wrong local
minima.

Three options, in order of effort:

- **A — Derive from elements (recommended first step)**  
  At expand time, `physics.py` already computes `R_wall`, `C_wall` per element
  (stored in `wall_chains`). Expose these as the nominal for wall-chain params
  (`wall_label.R`, `wall_label.C`). For zone `C` nodes: derive from room volume
  × air volumetric heat capacity (1200 J/m³K) + furnishings estimate.  
  No new API needed — enrich the RC model node fields so `n.R` / `n.C` already
  hold the element-level physical estimates.

- **B — Warm start from a previous fit result**  
  If the study already has `result_params`, pre-fill `nominal` with those values
  in FitPanel (and tighten `sigma_log` accordingly). Already partially designed
  as M6.9 "Promote to priors".

- **C — Auto-scale from data**  
  Estimate τ = RC from the observed temperature signal (step response or
  autocorrelation). Back out a plausible R or C given the other. Useful when
  no physical knowledge is available.

#### M7.2 — Series resistor identifiability grouping

Currently `identifiability.group_params()` only groups **parallel** resistors
(same endpoint pair → one shared multiplier). **Series** resistors between two
zones are also unidentifiable individually — only their sum is observable.

Example: `R_si` (surface resistance) in series with `R_wall` (bulk wall
resistance) between the same two temperature nodes. Fitting them separately is
ill-posed; only `R_si + R_wall` is constrained by data.

Design:
- Detect series chains: a path of resistance nodes between two non-resistance
  nodes where all intermediate nodes are pure resistances (no mass, no source).
  Each such chain → one group (sum parameter).
- The group representative is the first key in chain order; fitted value is the
  total series R, distributed to members proportionally to their nominals.
- In `_patch_model`, handle `series_chain_label.R` similarly to wall chains.
- Expose in FitPanel as a single row `R_si + R_wall (Mur SE) [m²K/W]` with
  combined nominal = sum of member nominals.

Note: `Rsi` and `Rse` (surface resistances, small, ~0.01–0.04 m²K/W) are
often the dominant series-identifiability issue in practice. A simpler fix is
to just **freeze** them by default (check `fixed: true`) in FitPanel, since
their value is well-known and not worth fitting.  This may be sufficient for M7.

---

## Backlog

### ~~Heavy wall — chain-N discretization~~ ✓ done

**Implemented:**
- `_opaque_chain_n()` — `max over layers of ceil(d/δ)` at 24h period, computed in `expand()`.
- `_opaque_C_total()` — `area × Σ(ρ·cp·d)` per layer.
- `_expand_opaque()` emits N identical RC lumps flanked by R_se / R_si.
  Outdoor side is detected automatically from the boundary node type; R_se and
  solar gain are placed on the correct side regardless of `between` order.
- `solar_absorptance` field on opaque elements: injects `α·A·solar_signal` as a
  source node into the outer surface mass node.
- `_patch_model()` fans out element-level `(label.R, label.C)` fit params to all
  N lump nodes via `model["wall_chains"]`.
- Wall mass node labels: `[outer]` / `[inner]` / `[wall]` instead of `[0]` / `[N-1]`.
- Opaque element editor: `solar α` numeric input (0–1, step 0.05) with tooltip.
- Opaque element row: `×N` chain badge in key figures, sourced from `rcModel.wall_chains`
  passed down from `+page.svelte` (reuses the already-fetched expand result, no extra call).
- Simulation chart: wall mass nodes (`m_*`) hidden by default (`show: false`), togglable via legend.
- House panel row layout: 2-line grid — row 1: icon | label | connectivity | signals | role;
  row 2: chevron | figures (full width).

**UI — still to do:**
- RC graph: render the N lump nodes + interior resistances visually in series
  between the two zone nodes, with R_se/R_si on each end.

### Parallel/series resistance identifiability

Parallel resistors sharing the same node pair: only the effective parallel R
is observable from temperature data. Series resistors between the same two
zones: only the sum is observable.

**Design decisions:**
- Keep individual element params with their own priors. The prior encodes
  construction knowledge (material, thickness) and can resolve elements when
  priors are sufficiently different.
- `group_params()` in `identifiability.py` already handles parallel grouping:
  collapses to one scale multiplier, freezes the nominal ratio.
- **To add:** same grouping logic for series resistors — detect chains where
  only the sum is identifiable, collapse to one multiplier.
- Do not reparametrize to effective values by default; let tight priors
  separate individual elements when the information is there.

### Initial state (T₀) for forward simulation

~~`y0_uniform` — single uniform temperature for all mass nodes, exposed in the UI
as a radio (`auto` / `uniform` + numeric input), sent to `/simulate/run` and `/fit/run`.~~ ✓ done

Still to do:

- **Burn-in / warm-up** — prepend a warm-up window (e.g. 24–48 h) before the study
  range, discard it, use the final state as T₀. Cheap, no extra solver. Length should
  be a few multiples of the dominant time constant (wall RC). Simplest to implement.
  Add `mode: "burnin"` with `burnin_days: int` (default 2).
- **Periodic steady-state** — assume the system is periodic over the study range;
  iterate: run one period, feed final state back as T₀, repeat until convergence.
- **Per-node T₀** — show one input per mass node (labels from `rcModel`), pre-filled
  with the uniform value, so the user can override individual nodes.

### Other

- **Material library extension** — `brique_creuse`, `stone_rubble`,
  `lime_plaster`, `wood_floor`, `tile_clay`, `concrete_slab`.
- **Materials panel** (left-nav) — browser/editor for the library.
- **Copy elements between houses** — select elements from one house, paste
  into another.
- **House UI v2** — 2D floor-plan canvas.
- **LLM-assisted model builder** — house description → LLM → initial house.
- **MCMC corner plot** — marginal histograms per param.

---

## Changelog

- **2026-06** — Working fit (M6 partial) — `house_name`+`study_id` context on `/fit/run`;
  `param_overrides` on `/simulate/run` patches RC model before solve for post-fit charts;
  `y0_uniform` propagated to both `/fit/run` and post-fit `/simulate/run`; FitPanel uses
  house/study API (no client-side model patching); `RangeSelect` extracted as shared component.

- **2026-06** — Heavy wall UI — `solar α` field in opaque editor; `×N` chain badge in row
  key figures (reuses `rcModel.wall_chains` from parent, no extra API call); wall mass node
  labels now `[outer]`/`[inner]`/`[wall]`; wall mass nodes hidden by default in sim chart;
  house panel rows use 2-line layout (label+connectivity on row 1, figures full-width on row 2).

- **2026-06** — Right pane rework — 3 fixed tabs: RC Graph (per-house, read-only),
  Studies (table with label/start/end/type/status columns; "+ Run" and "+ Fit" buttons),
  Simulation (study detail: time range, solver, run/fit action, charts); study type is now
  set at creation (`type: "run"|"fit"`) — a study is one or the other, not both; "Create
  study" removed from HousePanel toolbar.

- **2026-06** — House UI improvements — inline house label editor in HousePanel toolbar;
  delete house button (with confirm) + `DELETE /houses/{name}` backend endpoint; Studies
  section removed from left nav — all study navigation (Studies list, Simulation,
  Topology, Inputs, Run, Fit, RC, JSON tabs) moved into the right pane of the house split
  view; study save bar with back button replaces left-nav Save.

- **2026-06** — M4: New data model — `houses/` directory replaces single `house.json`; houses
  have embedded studies; `GET /houses`, `GET /houses/{name}`, `PUT /houses/{name}`,
  `POST /houses/{name}/studies`, `PUT/DELETE /houses/{name}/studies/{id}` endpoints;
  `expand()` drops `selection` arg — room/element `role` field (`mass`|`boundary`|`fixed`)
  controls node type; `model_hash()` (SHA-256 of elements, 12 hex chars) computed on every
  save and stored on run/fit results with stale flag; `house_name`+`study_id` context on
  `/simulate/run` and `/fit/run` persists result record into house JSON; UI: multi-house
  picker home screen, studies embedded in house, role badge + role selector in HousePanel.

- **2026-06** — House split view UI — simulation pane reworked: 1/3 house + 2/3
  sim split; toolbar add-buttons on own row; "Create study" fires immediately
  (no name dialog); sim pane has two tabs: *Simulation* (date range picker with
  duration presets + solver radios + Run/Fit/Show-inputs bar + charts) and *RC
  graph*; `SimulationRun` gains `hideControls` / `onready` props so the pane
  owns the control bar while the component owns chart state.
- **2026-06** — Study UUID (M3) — study IDs are now UUID4; `label` is the
  display name; save goes in-place for user studies, forks a new UUID for
  examples; duplicate auto-generates UUID.
- **2026-06** — M3 partial: study spawning — `POST /house/expand` (preview),
  `POST /studies/from_house` (expand + persist); house toolbar "Create study"
  button opens modal → calls backend → opens new study.
- **2026-06** — Element signals (M2) — `input_signal` / `obs_signal` on rooms
  and outdoor; house row icons; signal fields with InfluxDB autocomplete.
- **2026-06** — UUID + label (M1c) — schema v0.2: all element/room ids are
  UUIDs, `label` free-editable; `outdoor` and `ground` as typed elements;
  `house.json` rewritten.
- **2026-06** — House view: grid + split view — CSS grid columns; toolbar;
  split layout; row-click to expand; key figures client-side.
- **2026-06** — House view: flat list (`HousePanel.svelte` rewrite).
- **2026-06** — Fit charts: temperatures with observed overlay, inputs, residuals.
- **2026-06** — Identifiability module (parameter correlation analysis).
- **2026-06** — Parameter estimation: `solver/fit.py` (NLS + MCMC) +
  `POST /fit/run` + Fit tab UI.
- **2026-06** — Stale/save cycle (dirty Save badge, stale Run banner).
- **2026-05** — UI layout refactor: Home / Topology / Inputs / Run / Fit tabs.
- **2026-05** — Study persistence: `GET/POST /studies`, duplicate, `house.json`.
- **2026-05** — ZOH solver (`scipy.signal.cont2discrete` + `dlsim`).
- **2026-04** — `simulate_ivp` (BDF); `assemble()` — graph → `AssembledSystem`.
- **2026-03** — Svelte graph editor, FastAPI backend, material library.
