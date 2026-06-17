# Project roadmap

## Architecture

```
FastAPI backend  (thermal/)
HTML + vanilla JS + Plotly.js frontend  (frontend/)
```

A "simulation" is a single draw from the prior — same code path as Bayesian fit,
just with theta fixed to the prior mean.  One endpoint covers both.

---

## Phase 1 — Room description UI + prior display  ← current focus

### Backend

- [x] `thermal/models.py` — Room, EnvelopeElement, MaterialLayer dataclasses
- [x] `thermal/iso6946.py` — U-value, UA, thermal mass per element
- [x] `thermal/priors.py` — build_priors(room) → ParameterPrior per parameter
- [ ] `thermal/api_models.py` — Pydantic v2 schemas for all request/response types
      - `MaterialLayerIn`, `EnvelopeElementIn`, `RoomIn`
      - `Contribution`, `ParameterPriorOut`, `RCModelOut`
      - `RCModelOut` = the 2R2C prior bundle: H_env, H_ve, C_wall, C_room, alpha_eff
        each with mu, sigma, unit, and ordered list of contributions
- [ ] `api.py` — FastAPI app
      - `GET  /api/materials` → list of available material keys + display names
      - `POST /api/room/rc_model` → RoomIn → RCModelOut  (priors from description)
      - `POST /api/room/simulate` → RoomIn + weather params → hourly T° + energy
        (theta fixed to prior means = deterministic forward run)
      - `POST /api/room/fit` → RoomIn + observed T° log → posterior RCModelOut
        (theta optimised / sampled; same model, different theta source)
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

## Phase 2 — Forward simulation

- [ ] Refactor `thermal/rc_simulation.py` to accept explicit theta
      (H_env, H_ve, C_wall, C_room, alpha_eff) instead of computing from Room
      so the same function works for prior-mean run and posterior samples
- [ ] `POST /api/room/simulate` — runs with theta = prior means
      returns hourly T_in, T_sol_air, Q_heating, Q_cooling
- [ ] Frontend: weekly temperature plot (T_in vs T_out vs T_sol_air)
      showing the thermal lag effect on the heavy wall

---

## Phase 3 — Bayesian identification

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
