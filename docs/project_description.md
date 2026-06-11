# thermogram — project description

Current state of the sub-project. Updated when architecture changes, not per-task.
For open work see [todo.md](todo.md). For setup see [README.md](README.md).

---

## What it does

Model a house room-by-room as a thermal RC network, simulate it against sensor
data from InfluxDB, and fit model parameters to identify unknown thermal
properties of an existing building.

The user describes the building with physical elements (rooms, walls, windows,
air exchanges). The system derives the RC graph automatically, runs forward
simulations, and estimates parameters (λ, UA, capacitance) by fitting to
measured temperatures.

---

## Data model

### House (`houses/<name>.json`)

One file per house. The RC model is derived from it on demand — not stored.
Studies are embedded in the house file.

```json
{
  "name": "maison_test",
  "label": "Chambre",
  "schema_version": "0.3",
  "rooms": [
    {
      "id": "<uuid4>",
      "label": "Chambre",
      "role": "mass",
      "a": 5, "b": 5, "c": 3,
      "furniture_factor": 4.5,
      "obs_signal": "zigbee2mqtt/temperature?name=chambre"
    }
  ],
  "elements": [
    {
      "id": "<uuid4>",
      "kind": "outdoor",
      "role": "boundary",
      "label": "Extérieur",
      "obs_signal": "open_meteo/temperature_2m?location=home",
      "solar_signal": "open_meteo/shortwave_radiation?location=home"
    },
    {
      "id": "<uuid4>",
      "kind": "opaque",
      "label": "Mur SE",
      "between": ["<room_uuid>", "<outdoor_uuid>"],
      "a": 4, "b": 2.5,
      "orientation": "SE", "tilt": 90,
      "layers": [
        { "material": "brick_full", "thickness": 0.30 },
        { "material": "rock_wool",  "thickness": 0.10 }
      ]
    }
  ],
  "studies": [ ... ]
}
```

**Element kinds**: `room`, `outdoor`, `ground`, `opaque` (wall/roof/floor),
`glazing` (window/door), `air_exchange`.

**Room/element `role`**:
- `"mass"` — temperature is unknown, solved for (default for rooms)
- `"boundary"` — temperature prescribed by `obs_signal` at runtime
- `"fixed"` — temperature is a known constant (e.g. ground = 10 °C)

`outdoor` and `ground` elements are always boundary nodes regardless of role.

### Model hash

SHA-256 of the canonical JSON of `elements + rooms` (keys sorted, no
whitespace), first 12 hex chars. Recomputed on every `GET /houses/{name}`.
Stored on each run/fit result so the UI can flag stale studies.

### Study (embedded in house)

```json
{
  "id":           "<uuid4>",
  "label":        "Winter 2024",
  "type":         "run",
  "start":        "2024-01-01",
  "end":          "2024-02-28",
  "inputs":       { "<node_id>": "open_meteo/temperature_2m?location=home" },
  "observations": { "<node_id>": "zigbee2mqtt/temperature?name=chambre" },
  "solver":       "zoh",
  "run": {
    "model_hash": "a3f9bc...",
    "timestamp":  "20240115T143022",
    "settings":   { "solver": "zoh", "start": "...", "end": "...", "dt_minutes": 15 }
  }
}
```

A study is either `type: "run"` (forward simulation) or `type: "fit"`
(parameter estimation). The RC model is **not stored in the study** — it is
re-derived from the house via `expand()` every time a run or fit is triggered.
The `run.model_hash` / `fit.model_hash` field tracks whether the house has
changed since the last run, driving the stale flag in the UI.

### Signal name convention

```
measurement/field               # open_meteo/temperature_2m
measurement/field?tag=value     # zigbee2mqtt/temperature?name=salon
```

Stored in `study.inputs` (node_id → signal_name) and `study.observations`.
The mapping is runtime config — not baked into the house or the RC graph.

---

## Physics layer — `expand()`

`solver/physics.py` — `expand(house) → (rc_model, expansion_map)`

Translates physical element descriptions into the RC graph the solver sees.
Pure function, no I/O. Called on every run/fit request.

**Element → RC nodes**:

| Element kind | RC nodes produced |
|---|---|
| `room` | one `mass` node (capacitance from volume × air + furniture factor) |
| `outdoor` / `ground` | one `boundary` node (T forced from signal) |
| `opaque` | N identical RC lumps in series between the two zone nodes, with fixed surface resistances R_se and R_si on each end; `chain_n` derived from material properties |
| `glazing` | one resistance (U·A) + solar source node |
| `air_exchange` | one resistance (1 / ACH·V·ρCp) |

Material library in `data/materials/*.json` (brick, concrete, rock wool, …).

`expansion_map: { house_uuid → [rc_node_id, ...] }` — maps each house element
back to the RC nodes it produced. Used for results-on-house projection (M5).

---

## Solver pipeline

Three stages, each independently testable:

```
expand(house) → rc_model → assemble(rc_model) → simulate / fit
```

1. **`expand(house)`** — physical elements → R/C graph (see above).
2. **`assemble(model) → AssembledSystem`** — graph → `(A, B_boundary, B_source)`
   matrices. Resistance nodes are eliminated (Schur complement) during assembly.
3. **`simulate_ivp` / `simulate_zoh`** — pure numerics, no I/O.

```python
@dataclass
class AssembledSystem:
    A: np.ndarray           # [n_mass × n_mass]
    B_boundary: np.ndarray  # [n_mass × n_boundary]
    B_source: np.ndarray    # [n_mass × n_source]
    mass_ids: list[str]
    boundary_ids: list[str]
    source_ids: list[str]
```

### Solver choice

- **`simulate_ivp(BDF)`** — handles stiffness from the ~30× C ratio (thick
  wall vs room air). Good for exploration and verification.
- **`simulate_zoh`** — ZOH matrix exponential: `x[k+1] = Ad·x[k] + Bd·u[k]`,
  exact for piecewise-constant inputs on a uniform grid. O(n³) once to
  precompute, O(n²) per step. Required for optimisation / MCMC.

Uses `scipy.signal.cont2discrete(..., method='zoh')` + `scipy.signal.dlsim`.

---

## Parameter estimation (`solver/fit.py`)

1. **`build_forward(model, inputs, observations, fit_config, start, end, ...)`**
   returns a `log_params_vec → residuals` closure. Params in log-space; patches
   the model dict, re-assembles and re-discretises on every call.
2. **`fit_nls`** — `scipy.optimize.least_squares` (LM). Log-normal priors as
   extra residual terms. Returns best-fit params + covariance-derived std + cost.
3. **`fit_mcmc`** — `emcee` ensemble sampler, 20% burn-in, auto-thinning by
   autocorrelation time. Returns posterior mean/std + acceptance rate.

Param key format: `element_label.field_name` (e.g. `mur_SE.R`, `mur_SE.C`). For chained walls, `_patch_model()` maps the two element-level DOF `(R_wall, C_wall)` onto the N internal nodes before each iteration.

---

## API (`api/main.py`)

FastAPI on port 8001.

| Route | Purpose |
|---|---|
| `GET  /houses` | list all houses (name, label, n_rooms, n_elements, n_studies, model_hash) |
| `GET  /houses/{name}` | full house JSON with `_model_hash` and `_stale_*` flags on studies |
| `POST /houses` | create a new house |
| `PUT  /houses/{name}` | save house (strips computed `_` fields before writing) |
| `DELETE /houses/{name}` | delete house file |
| `POST /houses/{name}/expand` | `expand(house) → {model, expansion_map}` — preview, no persist |
| `POST /houses/{name}/studies` | create a study (auto-populates inputs from element signals) |
| `GET  /houses/{name}/studies/{id}` | single study with stale flags |
| `PUT  /houses/{name}/studies/{id}` | update study |
| `DELETE /houses/{name}/studies/{id}` | remove study |
| `POST /simulate/run` | expand house, fetch inputs from InfluxDB, run solver, persist run record, return `{t, nodes, meta, rc_model}` |
| `POST /fit/run` | expand house, fetch signals, run NLS or MCMC, persist fit record, return params + `rc_model` |
| `POST /fit/preview-groups` | identifiability analysis — group correlated parameters |
| `GET  /signals` | list all `measurement/field?tag=val` from InfluxDB |
| `GET  /series?signal=&start=&end=` | fetch + resample to 15 min |

`/simulate/run` and `/fit/run` both require `house_name` + `study_id` —
they load the house, call `expand()`, run the solver, and persist the result
record (with `model_hash` + timestamp) back into the house JSON.

---

## UI (`ui/`)

SvelteKit + uPlot. Single-page app.

### Layout

```
┌─ left nav ──┐  ┌─── house pane ───┐  ┌──── study pane (tabs) ────────────┐
│ Materials   │  │ HousePanel        │  │ [RC Graph] [Studies] [Simulation] │
│ House       │  │ rooms + elements  │  │                                   │
│             │  │ edit in place     │  │ RC Graph: current expand() result │
│             │  │                   │  │ Studies:  table + + Run / + Fit   │
│             │  │                   │  │ Simulation: controls + charts     │
└─────────────┘  └───────────────────┘  └───────────────────────────────────┘
```

House picker home screen when no house is open. Split view (house left, study
right) once a house is open.

### Right pane — three fixed tabs

**RC Graph** — always shows the current `expand(house)` result (house-level,
not study-level). Updated whenever the house reloads. Read-only.

**Studies** — table of all studies embedded in the house (label, start, end,
type badge, stale/done status). `+ Run` and `+ Fit` buttons create new studies.
Delete button per row.

**Simulation** — active when a study is selected. Header bar with label, type
badge, Save button. Control bar: date range (dates or duration+presets),
IVP/ZOH radio, Run/Fit button, Show inputs toggle. Charts: temperatures (mass
nodes + boundary overlay), input power (source nodes), residuals (if
observations set).

### Stale / dirty

- **House dirty** (`●` on Save): `house` state differs from `houseSavedSnapshot`.
- **Study dirty** (`●` on study Save): `{inputs, observations, start, end, solver}`
  differs from last saved snapshot.
- **Sim stale** (`⚠` banner in charts): same snapshot differs from last run.
- **Study stale** (`⚠ stale` in Studies table): `run.model_hash` or
  `fit.model_hash` differs from the current house `model_hash` — the house
  elements changed after this study was last run.

---

## Project structure

```
thermogram/
  data/
    houses/              one .json per house (elements + embedded studies)
    materials/           material library (brick, concrete, rock wool, …)
  thermogram/            python package
    solver/
      physics.py         expand(house) → (rc_model, expansion_map)
      assemble.py        rc_model → AssembledSystem (A, B matrices)
      simulate.py        simulate_ivp + simulate_zoh
      fit.py             build_forward + fit_nls + fit_mcmc
      identifiability.py group_params — correlated parameter analysis
      tests/
    api/
      main.py            FastAPI app
      influx.py          InfluxDB fetch + resample
      config.py          env config (MINIHA_INFLUX_* vars)
  ui/
    src/
      routes/+page.svelte       app shell, state, all API calls
      lib/HousePanel.svelte     house element list + inline editors
      lib/GraphView.svelte      RC graph canvas (read-only view)
      lib/SimulationRun.svelte  run/fit charts (temperatures, power, residuals)
      lib/FitPanel.svelte       fit params + observations config
      lib/InputsPanel.svelte    signal assignment + preview
      lib/MaterialsPanel.svelte material library browser
      lib/PropertiesPanel.svelte node/edge inspector (legacy RC editor)
      lib/SignalPicker.svelte   InfluxDB signal autocomplete
```

---

## Key design decisions

- **RC model derived, never stored.** `expand(house)` is called on every
  run/fit. Studies store only inputs/range/solver + the run/fit result record.
  No stale embedded topology.
- **House is the source of truth.** All physical knowledge lives in the house
  JSON. Studies are lightweight run configurations pointing at it.
- **Stale flag via model hash.** SHA-256 of elements detects house changes
  without diffing the full JSON. Stale is informational — the user decides when
  to re-run.
- **Solver split.** `solve_ivp(BDF)` for correctness/debug, ZOH for
  optimisation/MCMC. Same `AssembledSystem` input.
- **Log-space params.** Ensures positivity (R, C > 0) without constraints.
  Log-normal priors naturally express order-of-magnitude uncertainty.
- **Signals separate from topology.** `inputs` and `observations` are
  node_id → signal_name maps in the study, not in the RC graph. The topology
  is reusable across datasets and time ranges.
- **Multi-house.** `houses/` directory, one file per house. House picker on
  home screen. Studies are embedded in their house file.
- **Opaque wall discretization: N uniform lumps, 2 DOF fit.** Thick walls are
  discretized into N identical RC lumps in series (`R_wall/N`, `C_wall/N` each),
  flanked by fixed surface resistances R_se and R_si. `chain_n = max over layers
  of ceil(d_layer / δ_layer)` where `δ = sqrt(2·α/ω)` at the 24 h period.
  Fit parameters remain `(R_wall, C_wall)` per element regardless of N — the
  layer stack informs the prior, not the node count. This keeps the model
  identifiable and physically consistent with the sensor-based estimation
  philosophy: exact layer geometry is unknown for old buildings; only effective
  bulk properties can be inferred from temperature data. The N mass nodes give
  correct thermal lag without adding fit DOF. m_0 (outer surface) and m_{N-1}
  (inner surface) are accessible for future solar absorption and comfort
  (radiant asymmetry) use cases.
