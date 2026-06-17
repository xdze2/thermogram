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

## Phase 1 — Room description UI + prior display  ← current focus

### Backend

- [x] `thermal/models.py` — Room, EnvelopeElement, MaterialLayer dataclasses
- [x] `thermal/priors.py` — build_priors(room) → ParameterPrior per parameter
- [ ] `thermal/api_models.py` — Pydantic v2 schemas for all request/response types
      - `MaterialLayerIn`, `EnvelopeElementIn`, `RoomIn`
      - `ContributionOut`, `ParameterPriorOut`, `RCModelOut`
      - `RCModelOut` = the 2R2C prior bundle: H_env, H_ve, C_wall, C_room, alpha_eff
        each with mu, sigma, unit, and ordered list of contributions
- [ ] `api.py` — FastAPI app
      - `GET  /api/materials` → list of available material keys + display names
      - `POST /api/room/rc_model` → RoomIn → RCModelOut  (priors from description)
- [ ] `tests/test_api.py` — pytest + httpx
      - round-trip: RoomIn with brick wall → RCModelOut has expected H_env range
      - deterministic: same RoomIn twice → identical RCModelOut
      - materials endpoint returns non-empty list

### Frontend  (Phase 1 scope only)

- [ ] `frontend/index.html` — shell: two-column layout (editor left, priors right)
- [ ] `frontend/room_editor.js`
      - add / remove envelope elements (name, type, orientation, area)
      - layer stack editor per opaque element (material dropdown + thickness)
      - room-level fields: floor area, height, ACH, location
      - on any change: POST /api/room/rc_model and refresh prior display
- [ ] `frontend/prior_display.js`
      - render each RCModelOut parameter as additive log:
          H_env =
            + 13.4 W/K  ±2.0   │████████░░│  South wall [S]   U=1.34×10m²
            + 2.8  W/K  ±0.4   │██░░░░░░░░│  Window S   [S]   U=1.40×2m²
            ──────────────────
            = 16.2 W/K  ±2.1   (CV 13%)
      - unit-aware display (W/K, MJ/K, —)
      - uncertainty bar scaled to contribution fraction
- [ ] `frontend/materials.js` — fetch /api/materials on load, populate dropdowns

---

## Phase 1.5 — Input data specification

### Signal selection  ← done
- [x] `thermal/data_src/influx.py` — InfluxDB wrapper: `list_signals()`, `fetch_series()`
- [x] `GET /api/signals` — returns all queryable signal names; empty list if unreachable
- [x] Data sources block in left panel — T_int, T_ext, Q_sol each with a modal signal picker
      - searchable list populated from `/api/signals`
      - selected signal shown inline; "clear" to deselect

### Time range + data preview  ← next
- [ ] Date range selector in frontend (below data sources block)
      - start / end date inputs (ISO, whole-day granularity)
      - `+ N days` helper button to extend end date
- [ ] `GET /api/data?signals=…&start=…&end=…` — fetch selected signals, return JSON timeseries
      - calls `fetch_series()` per signal, aligns to common index, returns `{signal: [[t, v], ...]}`
- [ ] Input data preview panel (right column, below RC diagram)
      - Plotly.js time-series chart — one trace per selected + assigned signal
      - auto-fetches when date range or signal selection changes (debounced)
      - shows gap / NaN regions visually

---

## Phase 2 — Bayesian identification

- [ ] `thermal/state_space.py`
      - build A, B matrices for 2R2C system from theta
      - discrete-time ZOH transition (matrix exponential)
      - Kalman filter likelihood p(T_obs | theta, weather)
- [ ] `POST /api/room/fit`
      - input: RoomIn + CSV/JSON of observed T° (hourly) + weather year
      - uses scipy.optimize (MAP) or emcee (full posterior)
      - returns RCModelOut with posterior mu/sigma replacing prior
      - contributions log becomes: "prior: 13.4, posterior: 11.2 (pulled by data)"
- [ ] Frontend: prior vs posterior overlay plot per parameter (Plotly.js)
- [ ] Frontend: upload T° log (CSV drag-and-drop)

---

## Parking lot / later

- Multi-zone (inter-room heat transfer)
- Ground-coupled floor (ISO 13370)
- Shading masks
- Primary energy conversion (boiler/heat-pump COP)
- Export: PDF summary, EnergyPlus IDF snippet
