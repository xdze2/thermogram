# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Model a house room-by-room as a thermal RC network, simulate it against
sensor data, and fit model parameters (R, C, λ) to identify the thermal
properties of an existing building. Python solver + FastAPI backend,
SvelteKit frontend.

## Commands

```bash
uv sync                                   # install python deps
cd ui && npm install && npm run build     # build frontend (served by FastAPI)

# Start app — API + UI at http://localhost:8001
uv run uvicorn thermogram.api.main:app --reload --port 8001

# Frontend dev with hot reload (run alongside the API)
cd ui && npm run dev                      # http://localhost:5173

# Tests
uv run pytest thermogram/solver/tests     # all
uv run pytest thermogram/solver/tests/test_fit.py::TestFitNLS1R1C -q   # one class
```

Known broken state (see docs/todo.md Step 0): `pytest` is not yet a declared
dependency (`uv run --with pytest pytest ...` as a workaround) and the suite
fails on missing `data/examples/*.json` fixtures.

After any frontend change, `cd ui && npm run build` — FastAPI serves the
static build from `ui/build/`, not the dev server.

## Layout

Python code lives in the `thermogram/` package (`thermogram/api/`,
`thermogram/solver/`), installed editable via hatchling. Runtime data
(`data/`), the frontend (`ui/`), and JSON schemas (`schema/`) sit at the
repo root, **outside** the package — code reaches them via paths resolved
relative to `__file__` (e.g. `DATA_DIR` in `api/main.py`,
`_MATERIALS_DIR` in `solver/physics.py`). If you move a module, check its
`Path(__file__).parents[n]` computations.

## Architecture

Three-stage solver pipeline, each stage pure and independently testable:

```
house JSON → expand() → rc_model → assemble() → (A, B) → simulate / fit
            physics.py            assemble.py            simulate.py, fit.py
```

- **`solver/physics.py` — `expand(house)`**: physical elements (rooms,
  walls with material layers, glazing, air exchange) → RC graph + an
  `expansion_map` (element uuid → rc node ids). Opaque walls become N
  identical RC lumps in series (`chain_n` from material diffusivity at the
  24 h period) flanked by fixed surface resistances Rse/Rsi.
- **`solver/assemble.py`**: RC graph → `AssembledSystem` (A, B matrices);
  pure-resistance nodes are eliminated by Schur complement.
- **`solver/simulate.py`**: `simulate_ivp` (BDF, for verification — the
  system is stiff) and `simulate_zoh` (exact for piecewise-constant inputs,
  fast — required for fit/MCMC).
- **`solver/fit.py`**: `build_forward()` returns a log-params → residuals
  closure (re-patches + re-assembles the model each call); `fit_nls`
  (scipy least_squares + log-normal priors as residuals) and `fit_mcmc`
  (emcee). `_patch_model` fans element-level `(label.R, label.C)` out to
  the N wall-chain nodes via `model["wall_chains"]`.

Key invariants:

- **The house JSON is the sole source of truth; the RC model is derived,
  never stored.** `expand()` runs on every run/fit request. Studies (runs
  and fits) are embedded in the house file and store only config + results.
- **Staleness via model hash**: SHA-256 (first 12 hex chars) of canonical
  `elements + rooms` JSON, stored on each run/fit result, recomputed on
  load — drives the stale flags in the UI.
- **Signals are separate from topology**: `study.inputs` / `.observations`
  map rc node id → signal name (`measurement/field?tag=value`); data comes
  from InfluxDB at runtime (`api/influx.py`, resampled to 15 min).
- **Fit params live in log-space** to guarantee R, C > 0.

`api/main.py` is the single FastAPI app (port 8001): house/study CRUD,
`/simulate/run`, `/fit/run`, `/signals`, `/series`, plus static UI serving.
InfluxDB config via `MINIHA_INFLUX_*` env vars (`api/config.py`; optional
`.env` resolved relative to the repo's parent).

`ui/src/routes/+page.svelte` holds all app state and every API call;
`lib/*.svelte` components are presentational + callbacks. House data files
live in `data/houses/*.json` (user-edited at runtime — never use them as
test fixtures) and the material library in `data/materials/*.json`.

## Docs map — read before structural changes

- `docs/project_description.md` — **current** architecture, data model, API
  surface. Update it when architecture changes.
- `docs/todo.md` — the step-by-step plan to v1 (includes introducing a
  "pseudo layer" φ-space that will replace today's node-field fit params).
- `docs/modeling_pipeline.md` + `docs/implementation.md` — **target**
  design (beliefs/atoms/pseudos/views, agent loop, hot/cold path split).
  Mostly not implemented; don't confuse with current state.
- `docs/roadmap.md` — long-term wishlist.
