# Project roadmap

## Architecture

```
FastAPI backend  (thermal/)
HTML + vanilla JS + Plotly.js frontend  (frontend/)
```

The workflow is: user describes the room → RC priors are built from the description →
observed temperature log is uploaded → Bayesian fit updates the priors to a posterior.
No static U-value path. No forward simulation endpoint.

---

## Phase 1 — Room description UI + prior display ← current focus

### Backend

- [x] `thermal/models.py` — Room, EnvelopeElement, MaterialLayer dataclasses
- [x] `thermal/priors.py` — build_priors(room) → ParameterPrior per parameter
- [ ] `thermal/api_models.py` — Pydantic v2 schemas for all request/response types - `MaterialLayerIn`, `EnvelopeElementIn`, `RoomIn` - `ContributionOut`, `ParameterPriorOut`, `RCModelOut` - `RCModelOut` = the 2R2C prior bundle: H_env, H_ve, C_wall, C_room, alpha_eff
      each with mu, sigma, unit, and ordered list of contributions
- [ ] `api.py` — FastAPI app - `GET  /api/materials` → list of available material keys + display names - `POST /api/room/rc_model` → RoomIn → RCModelOut (priors from description)
- [ ] `tests/test_api.py` — pytest + httpx - round-trip: RoomIn with brick wall → RCModelOut has expected H_env range - deterministic: same RoomIn twice → identical RCModelOut - materials endpoint returns non-empty list

### Frontend (Phase 1 scope only)

- [ ] `frontend/index.html` — shell: two-column layout (editor left, priors right)
- [ ] `frontend/room_editor.js` - add / remove envelope elements (name, type, orientation, area) - layer stack editor per opaque element (material dropdown + thickness) - room-level fields: floor area, height, ACH, location - on any change: POST /api/room/rc_model and refresh prior display
- [ ] `frontend/prior_display.js` - render each RCModelOut parameter as additive log:
      H_env = + 13.4 W/K ±2.0 │████████░░│ South wall [S] U=1.34×10m² + 2.8 W/K ±0.4 │██░░░░░░░░│ Window S [S] U=1.40×2m²
      ──────────────────
      = 16.2 W/K ±2.1 (CV 13%) - unit-aware display (W/K, MJ/K, —) - uncertainty bar scaled to contribution fraction
- [ ] `frontend/materials.js` — fetch /api/materials on load, populate dropdowns

---

## Phase 1.5 — Input data specification

### Signal selection ← done

- [x] `thermal/data_src/influx.py` — InfluxDB wrapper: `list_signals()`, `fetch_series()`
- [x] `GET /api/signals` — returns all queryable signal names; empty list if unreachable
- [x] Data sources block in left panel — T_int, T_ext, Q_sol each with a modal signal picker - searchable list populated from `/api/signals` - selected signal shown inline; "clear" to deselect

### Time range + data preview ← done

- [x] Date range selector in frontend (below data sources block) - start / end ISO date inputs (YYYY-MM-DD), `+7d` / `+30d` / `+90d` helper buttons
- [x] `GET /api/data?signals=…&start=…&end=…` — fetch selected signals, return `{signal: [[t, v], ...]}`
- [x] Input data preview panel (right column, below RC diagram) - two Plotly subplots: temperatures (T_int, T_ext) on top; Q_sol area-filled below - auto-fetches on date range or signal selection change (debounced)
- [x] Full UI state persisted in localStorage (room fields, elements, signals, date range)
- [x] Fix Plotly crash when API returns empty data (purge chart instead of calling react with zero traces)
- [x] Fix `+7d` / `+30d` / `+90d` date arithmetic (was off by one day in timezones behind UTC)

---

## Phase 1.6 — Svelte migration ← done

Replace vanilla JS frontend with a Svelte + Vite app. FastAPI serves `frontend/dist/` as static files.

- [x] Scaffold Svelte + Vite app in `frontend_svelte/`
- [x] Configure Vite to build into `frontend/dist/`; update `api.py` static mount to `frontend/dist/`
- [x] Port current UI to Svelte components (room editor, prior display, signal picker, data preview)
- [x] Add `npm run build` / `npm run dev` to CLAUDE.md commands

---

## Phase 1.7 — Studies manager ← done

Backend and frontend for managing multiple studies (room + data spec + results bundles).

### Backend

- [x] `thermal/study.py` — `Study` Pydantic model: `id`, `name`, `created_at`, `updated_at`, `room`, `data_spec` (`{signals, start, end}`), `rc_prior`, `fit_result`
- [x] `thermal/study_store.py` — CRUD over `user_data/{id}.json`: list, load, save, delete, duplicate
- [x] New endpoints:
      `GET    /api/studies`              → list stubs (id, name, updated_at)
      `POST   /api/studies`              → create new study, return full Study
      `GET    /api/studies/{id}`         → full Study JSON
      `DELETE /api/studies/{id}`
      `PATCH  /api/studies/{id}/room`    → RoomIn → updates rc_prior in-place, returns RCModelOut
      `PATCH  /api/studies/{id}/name`    → rename study
      `POST   /api/studies/{id}/duplicate`
- [x] Drop old flat endpoints (`/api/room/rc_model`, `/api/data`); migrate `DataPreview` to `/api/studies/{id}/data`

### Frontend (Svelte)

- [x] `/` route — Studies list page: table of studies (name, updated_at), create, open, duplicate, delete, rename inline
- [x] `/study/:id` route — Study editor (current UI, hydrated from `GET /api/studies/{id}`)
      Replace localStorage persistence with implicit auto-PATCH on every field change
- [x] Study name editable inline in the editor header; breadcrumb back to studies list

---

## Phase 2 — Bayesian identification

### Revised RC model (2R2C)

```
T_sa(t) ──H_env──[C_wall]──H_int──┐
                                   ├──[C_room]── T_room (observed)
T_ext ──(H_ve + H_win)────────────┘
                                   │
                      Q_sol_win + Q_int
```

- `T_sa = T_ext + α_eff · G / h_ext`  — sol-air temperature (opaque surfaces only)
- `H_env = Σ U·A` opaque elements (walls, roof, floor) — drives sol-air path through C_wall
- `H_win = Σ U·A` windows — direct T_ext→C_room loss (lumped with H_ve or kept separate)
- `H_int` — fixed from ISO 6946: `H_int = A_opaque / (R_si + R_layers)`, not a free param
- `Q_sol_win = Σ SHGC·A·G_surface` per window — direct gain into C_room
- `α_eff` — area-weighted absorptivity of opaque outer surfaces

**5 free parameters:** `H_env`, `H_ve` (or `H_ve+H_win`), `C_wall`, `C_room`, `α_eff`

Notes:
- Per-orientation wall split deferred to later (one α_eff scalar for now)
- H_int fixed ratio keeps state-space identifiable
- Windows skip C_wall (solar gain direct to C_room, U-loss direct T_ext→C_room)

### Backend

- [x] `thermal/state_space.py` — 2R2C A/B matrices; H_int fixed from ISO 6946; ZOH via `scipy.signal.cont2discrete`; `forward_sim`, `sol_air_temperature`
- [x] Update `priors.py` — `H_env` opaque-only; window U·A in `H_ve` contributions; `H_int` returned in `RCModelOut`
- [x] Update README mermaid diagram to match revised model
- [x] `thermal/fit.py` — MAP via `scipy.optimize.minimize` (L-BFGS-B); log/logit-space params; returns `FitResult`
### Input data caching (replaces live-fetch preview)

Store fetched time-series inside the study JSON as `input_data`. Preview and fit both read from it — no live InfluxDB query at fit or render time.

```
study.input_data = {
  "signal_name": [[iso_timestamp, value], ...]   # one entry per selected signal
}
```

Workflow: user sets signals + date range → clicks "Fetch data" → `POST /api/studies/{id}/fetch_data` pulls from InfluxDB and writes `input_data` into study file → preview renders from cached data → fit reads same array.

- [ ] Add `input_data` field to `Study` model (`dict[str, list[list]] | None`)
- [ ] `POST /api/studies/{id}/fetch_data` — reads `data_spec`, pulls from InfluxDB, saves `input_data` in study, returns it
- [ ] Remove `GET /api/studies/{id}/data` (replaced by fetch_data + cached field)
- [ ] Update `DataPreview.svelte` — render from `study.input_data` (loaded with study), trigger re-render on fetch; replace live-fetch with "Fetch data" button
- [ ] `POST /api/studies/{id}/fit` — read `study.input_data`, run `fit.run_fit()`, store result in `study.fit_result`, return `FitResult`
- [ ] `GET  /api/studies/{id}/fit` — return cached `fit_result` (or 404 if not yet run)

### Frontend

- [ ] "Fetch data" button in DataSources panel; show row count + date range of cached data; spinner while fetching
- [ ] Fit trigger button in study editor; show spinner while running
- [ ] Prior vs posterior overlay in `PriorBlock.svelte` — show both mu±sigma when `fit_result` is present
- [ ] Contributions log annotation: "prior: 13.4 → posterior: 11.2 (pulled by data)"

---

## Parking lot / later

- Multi-zone (inter-room heat transfer)
- Ground-coupled floor (ISO 13370)
- Shading masks
- Primary energy conversion (boiler/heat-pump COP)
- Export: PDF summary, EnergyPlus IDF snippet
