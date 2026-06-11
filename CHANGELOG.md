# Changelog

- **2026-06** — Package layout — `api/` and `solver/` moved into a real `thermogram/`
  package dir; editable install no longer relies on a `.pth` pointing at the repo's
  parent dir; `Path(__file__)` lookups (data, materials, ui/build, test fixtures)
  adjusted; run/test commands unchanged except test path
  (`uv run pytest thermogram/solver/tests`). Docs: `todo.md` rewritten as the
  step-by-step v1 plan (pseudo-layer φ-space on the critical path); `CLAUDE.md` added.

- **2026-06** — Working fit (M6 partial) — `house_name` + `study_id` context on `/fit/run`;
  `param_overrides` on `/simulate/run` patches RC model before solve for post-fit charts;
  `y0_uniform` propagated to both `/fit/run` and post-fit `/simulate/run`; FitPanel uses
  house/study API (no client-side model patching); `RangeSelect` extracted as shared component.

- **2026-06** — Heavy wall UI — `solar α` field in opaque editor; `×N` chain badge in row
  key figures (reuses `rcModel.wall_chains` from parent, no extra API call); wall mass node
  labels now `[outer]` / `[inner]` / `[wall]`; wall mass nodes hidden by default in sim chart;
  house panel rows use 2-line layout (label + connectivity on row 1, figures full-width on row 2).

- **2026-06** — Right pane rework — 3 fixed tabs: RC Graph (per-house, read-only),
  Studies (table with label/start/end/type/status columns; "+ Run" and "+ Fit" buttons),
  Simulation (study detail: time range, solver, run/fit action, charts); study type is now
  set at creation (`type: "run" | "fit"`) — a study is one or the other, not both; "Create
  study" removed from HousePanel toolbar.

- **2026-06** — House UI improvements — inline house label editor in HousePanel toolbar;
  delete house button (with confirm) + `DELETE /houses/{name}` backend endpoint; Studies
  section removed from left nav — all study navigation (Studies list, Simulation,
  Topology, Inputs, Run, Fit, RC, JSON tabs) moved into the right pane of the house split
  view; study save bar with back button replaces left-nav Save.

- **2026-06** — New data model (M4) — `houses/` directory replaces single `house.json`; houses
  have embedded studies; `GET /houses`, `GET /houses/{name}`, `PUT /houses/{name}`,
  `POST /houses/{name}/studies`, `PUT/DELETE /houses/{name}/studies/{id}` endpoints;
  `expand()` drops `selection` arg — room/element `role` field (`mass` | `boundary` | `fixed`)
  controls node type; `model_hash()` (SHA-256 of elements, 12 hex chars) computed on every
  save and stored on run/fit results with stale flag; `house_name` + `study_id` context on
  `/simulate/run` and `/fit/run` persists result record into house JSON; UI: multi-house
  picker home screen, studies embedded in house, role badge + role selector in HousePanel.

- **2026-06** — House split view UI — simulation pane reworked: 1/3 house + 2/3 sim split;
  toolbar add-buttons on own row; "Create study" fires immediately (no name dialog); sim
  pane has two tabs: *Simulation* (date range picker with duration presets + solver radios
  + Run/Fit/Show-inputs bar + charts) and *RC graph*; `SimulationRun` gains `hideControls` /
  `onready` props so the pane owns the control bar while the component owns chart state.

- **2026-06** — Study UUID (M3) — study IDs are now UUID4; `label` is the display name;
  save goes in-place for user studies, forks a new UUID for examples; duplicate
  auto-generates UUID.

- **2026-06** — Study spawning (M3 partial) — `POST /house/expand` (preview),
  `POST /studies/from_house` (expand + persist); house toolbar "Create study" button opens
  modal → calls backend → opens new study.

- **2026-06** — Element signals (M2) — `input_signal` / `obs_signal` on rooms and outdoor;
  house row icons; signal fields with InfluxDB autocomplete.

- **2026-06** — UUID + label (M1c) — schema v0.2: all element/room ids are UUIDs, `label`
  free-editable; `outdoor` and `ground` as typed elements; `house.json` rewritten.

- **2026-06** — House view: grid + split view — CSS grid columns; toolbar; split layout;
  row-click to expand; key figures client-side.

- **2026-06** — House view: flat list — `HousePanel.svelte` rewrite.

- **2026-06** — Fit charts — temperatures with observed overlay, inputs, residuals.

- **2026-06** — Identifiability module — parameter correlation analysis.

- **2026-06** — Parameter estimation — `solver/fit.py` (NLS + MCMC) + `POST /fit/run` +
  Fit tab UI.

- **2026-06** — Stale/save cycle — dirty Save badge, stale Run banner.

- **2026-05** — UI layout refactor — Home / Topology / Inputs / Run / Fit tabs.

- **2026-05** — Study persistence — `GET/POST /studies`, duplicate, `house.json`.

- **2026-05** — ZOH solver — `scipy.signal.cont2discrete` + `dlsim`.

- **2026-04** — Solver core — `simulate_ivp` (BDF); `assemble()` — graph → `AssembledSystem`.

- **2026-03** — Initial stack — Svelte graph editor, FastAPI backend, material library.
