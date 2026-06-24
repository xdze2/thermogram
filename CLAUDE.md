# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the dev server
uv run uvicorn api:app --reload   # → http://localhost:8000

# Frontend (Svelte + Vite) — run from frontend/
npm run dev    # → http://localhost:5173 (proxied to FastAPI)
npm run build  # → builds into frontend/dist/ (served by FastAPI)

# Run all tests
uv run pytest

# Run a single test
uv run pytest tests/test_api.py::test_rc_model_brick_room_h_env_range
```

## Architecture

This app computes Gaussian priors on five thermal RC parameters from a room description, using ISO 6946 physics. Phase 2 (not yet implemented) will fit those priors to observed sensor data via Bayesian inference.

**Request flow:** browser form → `POST /api/room/rc_model` → `build_priors(room)` → `RCModelOut` → prior display with per-element contribution bars.

### RC model (2R2C)

```
T_sa(t) ──R_ext──[C_wall]──R_int──[C_room]
                                      │
                                Q_int + Q_sol_win
                                R_ve ── T_out
```

Five parameters: `H_env` (W/K), `H_ve` (W/K), `C_wall` (J/K), `C_room` (J/K), `alpha_eff` (—).

### Key modules

- **`thermal/priors.py`** — `build_priors(room) → RCModelOut`. Central function; all five parameter priors computed here with per-element contributions and quadrature-summed uncertainties.
- **`thermal/api_models.py`** — Pydantic v2 models: `Room`, `EnvelopeElement`, `MaterialLayer`, response types (`RCModelOut`, `ParameterPriorOut`, `ContributionOut`).
- **`thermal/iso6946.py`** — U-value from layer stack (EN ISO 6946:2017 series resistance). `element_u_value(element)` respects `u_value_override` if set.
- **`thermal/materials_db.py`** — `MATERIALS: dict[str, MaterialSpec]`. `MaterialSpec` carries `lambda_`, `rho`, `cp`; `is_heavy` (ρ > 500 kg/m³) controls which layers count toward `C_wall`.
- **`thermal/rc_simulation.py`** — Hourly Euler simulation (phase 2 use); not called by the prior endpoint.
- **`api.py`** — Endpoints: `GET /api/schema`, `GET /api/materials`, `GET /api/modules` (module catalogue), `GET /api/signals`, study CRUD + `PATCH …/room`, `GET …/topology` (assembled RC schematic SVG/PNG). `RCModelOut` carries the active-module report (`modules`, `signals_required`, `n_states`, `identifiability_warning`). Serves `frontend/dist/` as static files on `/` (falls back to `frontend/` if dist missing).

### Frontend

Svelte + Vite app in `frontend/`, built into `frontend/dist/` (served by FastAPI). DaisyUI 5 + Tailwind CSS v4.

- **`src/App.svelte`** — top-level layout, init, theme switcher, compute loop (debounced 180 ms POST)
- **`src/lib/store.js`** — all state as Svelte stores + localStorage persistence
- **`src/lib/RoomFields.svelte`** — room name/area/height/ACH/lat/lon
- **`src/lib/ElementCard.svelte`** — collapsible card per envelope element with layer stack editor
- **`src/lib/DataSources.svelte`** — T_int/T_ext/Q_sol signal rows + time range selector
- **`src/lib/SignalPicker.svelte`** — modal with search + select/clear
- **`src/lib/PriorBlock.svelte`** — per-parameter prior display with contribution bars
- **`src/lib/DataPreview.svelte`** — Plotly chart, reacts to store changes
- **`src/lib/api.js`** — `fetchJson` / `postRcModel`
- **`src/lib/format.js`** — `fmt` / `scaleUnits`

Dev server (`npm run dev`) proxies `/api/*` to FastAPI on port 8000. Mermaid rendered via jsDelivr CDN, re-rendered on theme change.

### Prior uncertainties (1-sigma relative)

| Parameter | Uncertainty |
|-----------|-------------|
| H_env | ±15% |
| H_ve | ±40% |
| C_wall | ±25% per element |
| C_room | ±60% |
| α_eff | ±0.15 absolute |

`C_room` uses a fixed weak prior of 20 kJ/(m²·K) × floor area — not derived from element layers.
