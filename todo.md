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

---

## Phase 1.6 — Svelte migration

Replace vanilla JS frontend with a Svelte + Vite app. FastAPI serves `frontend/dist/` as static files.

- [ ] Scaffold Svelte + Vite app in `frontend/` (or `frontend_svelte/` during transition)
      `npm create vite@latest frontend_svelte -- --template svelte`
- [ ] Configure Vite to build into `frontend/dist/`; update `api.py` static mount to `frontend/dist/`
- [ ] Port current UI to Svelte components (room editor, prior display, signal picker, data preview)
      Keep feature parity with current `app.js` before adding anything new
- [ ] Add `npm run build` / `npm run dev` to CLAUDE.md commands

---

## Phase 1.7 — Studies manager

Backend and frontend for managing multiple studies (room + data spec + results bundles).

### Backend

- [ ] `thermal/study.py` — `Study` Pydantic model: `id`, `name`, `created_at`, `updated_at`, `room`, `data_spec` (`{signals, start, end}`), `rc_prior`, `fit_result`
- [ ] `thermal/study_store.py` — CRUD over `user_data/{id}.json`: list, load, save, delete, duplicate
- [ ] New endpoints:
      `GET    /api/studies`              → list stubs (id, name, updated_at)
      `POST   /api/studies`              → create new study, return full Study
      `GET    /api/studies/{id}`         → full Study JSON
      `DELETE /api/studies/{id}`
      `PATCH  /api/studies/{id}/room`    → RoomIn → updates rc_prior in-place, returns RCModelOut
      `PATCH  /api/studies/{id}/data_spec` → {signals, start, end} → fetches + caches data, returns preview
      `GET    /api/studies/{id}/data`    → cached series (fetched on data_spec update)
- [ ] Drop old flat endpoints (`/api/room/rc_model`, `/api/data`) once frontend is migrated

### Frontend (Svelte)

- [ ] `/` route — Studies list page: table of studies (name, updated_at), create, open, duplicate, delete, rename inline
- [ ] `/study/:id` route — Study editor (current UI, hydrated from `GET /api/studies/{id}`)
      Replace localStorage persistence with implicit auto-PATCH on every field change
- [ ] Study name editable inline in the editor header; breadcrumb back to studies list

---

## Phase 2 — Bayesian identification

What about using:
from scipy.signal import cont2discrete, dlsim
from scipy.interpolate import interp1d

- [ ] `thermal/state_space.py` - build A, B matrices for 2R2C system from theta - discrete-time ZOH transition (matrix exponential) - Kalman filter likelihood p(T_obs | theta, weather)
- [ ] `POST /api/room/fit` - input: RoomIn + CSV/JSON of observed T° (hourly) + weather year - uses scipy.optimize (MAP) or emcee (full posterior) - returns RCModelOut with posterior mu/sigma replacing prior - contributions log becomes: "prior: 13.4, posterior: 11.2 (pulled by data)"
- [ ] Frontend: prior vs posterior overlay plot per parameter (Plotly.js)
- [ ] Frontend: upload T° log (CSV drag-and-drop)

---

## Parking lot / later

- Multi-zone (inter-room heat transfer)
- Ground-coupled floor (ISO 13370)
- Shading masks
- Primary energy conversion (boiler/heat-pump COP)
- Export: PDF summary, EnergyPlus IDF snippet
