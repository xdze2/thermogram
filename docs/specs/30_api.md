# 30 — API Contract (FastAPI ↔ Svelte)

**Status: BUILT.** All endpoints below are live. The signal-grouping model
([`15_signals_and_grouping.md`](15_signals_and_grouping.md)) is the actual contract: modules
are derived from element boundaries by the server's grouping rule; per-element boundary and
treatment fields are present on all registry and document shapes; `GET /assembly` returns
`required_signals`. The freeze discipline applies: change the contract here first, then code.

> **Note for the state spec.** Line item: *"After any mutation the frontend re-fetches to
> refresh all derived views."* The *mechanism* for that (the store-owned `applyMutation`
> invariant, re-pulling **both** `/document` and `/assembly`) is specified in
> [`10_state.md`](10_state.md). This contract defines the endpoints; `10_state.md` defines
> how the frontend must call them.

---

## Global conventions

- All model-scoped routes: `/api/models/{model_id}/…`, where `{model_id}` is a model **UID**.
- Models are **persisted locally** (see [model management](#model-management) below). Each model
  is a UID-addressed document auto-saved to `user_data/{uid}.json`; the server loads all saved
  models at startup. `name` is a mutable label; the UID is stable (rename ≠ new UID). A `"default"`
  model is seeded on first run when `user_data/` is empty. *(This supersedes the original 4a
  "single in-memory `default`, no save/load/list" rule — see CLAUDE.md amendment.)*
- No `study_id` anywhere. Leaf endpoints (`/simulate`, `/identifiability`) receive their data in the request body.
- IDs are server-assigned opaque strings (e.g. `"e1"`, `"m0"`).
- Mutations return the affected resource. After any mutation the frontend re-fetches `/document` **and** `/assembly` to refresh all derived views (see [`10_state.md`](10_state.md)).
- `GET /assembly` **never** returns HTTP 500 on a structurally incomplete room — it always returns partial data + `problems[]`.

---

## Model management

UID-addressed local persistence. These endpoints manage the set of saved models; the
model-scoped routes (document, assembly, CRUD, physics) operate on one model by its UID.
Model-management mutations are **not** room-document mutations — they do not trigger the
`/document` + `/assembly` re-pull invariant; the frontend re-lists `/api/models` instead.

```
GET    /api/models                 -> [{uid, name}]                list saved models
POST   /api/models       {name?}   -> {uid, name}                  create empty model (name defaults "Untitled")
GET    /api/models/examples        -> [{key, name}]                available example templates
POST   /api/models/from_example  {example_key, name?} -> {uid, name}   copy an example into a NEW uid
PATCH  /api/models/{uid}  {name}   -> {uid, name}                  rename (label only; uid unchanged)
DELETE /api/models/{uid}           -> 204                          remove model + its user_data file
```

- `from_example` copies a canonical room (`caravan`, `heavy_wall`, `collinear`, `cellar`) into a
  fresh UID; the example originals are read-only templates and are never mutated. Returns `503`
  if examples are unavailable, `404` for an unknown `example_key`.
- `PATCH`/`DELETE` on an unknown `uid` return `404`.
- Auto-save: every model-scoped mutation persists `user_data/{uid}.json` before returning.

---

## Shared types

### `FieldSchema`
```json
{
  "name": "area",
  "type": "float",          // "float" | "int" | "str" | "enum" | "list[layer]"
  "default": 0.0,           // optional
  "options": ["S","SE",…]   // only when type == "enum"
}
```

### `LayerSchema`
```json
{
  "fields": [
    {"name": "material", "type": "enum", "options": ["concrete", "brick", …]},
    {"name": "thickness", "type": "float"}
  ]
}
```

### `ElementTypeSchema`
```json
{
  "type_name": "OuterWall",
  "fields": [<FieldSchema>, …],
  "boundary": {"field": "orientation", "role": "solar+exterior"},
  "treatments": [
    {"key": "thermal_mass", "label": "Thermal-mass wall", "default": true},
    {"key": "simple_loss",  "label": "Simple loss"}
  ]
}
```

`boundary` describes how this element pins boundary signals. `treatments` is `[]` for element
types with no treatment knob (everything except heavy `OuterWall`). The frontend uses these
to render per-type boundary fields and the treatment radio group.

### `ModuleTypeSchema`
```json
{
  "type_name": "RoomMass",
  "owns": [],               // list of Channel names this module claims (engine metadata)
  "params": ["C_room"],
  "fields": [<FieldSchema>, …]
}
```

> **`owns` is engine metadata only.** It is present in the registry for diagnostics and the
> ownership-check panel. The frontend does **not** use it to gate routing controls — there
> are no routing controls.

### `Element` (resource)
```json
{
  "id": "e0",
  "type": "OuterWall",
  "label": "OuterWall",
  "fields": {"area": 10.0, "orientation": "S", "layers": [{"material": "concrete", "thickness": 0.2}], "alpha": 0.6, "treatment": "thermal_mass"},
  "budgets": {
    "CONDUCTION":        {"UA": 3.2, "shgcA": null, "alphaA": null, "C": null},
    "SOLAR_OPAQUE":      {"UA": null, "shgcA": null, "alphaA": 6.0, "C": null},
    "STORAGE":           {"UA": null, "shgcA": null, "alphaA": null, "C": 52000.0}
  }
}
```

`fields` includes boundary fields (e.g. `orientation`, `adjacent`, `adjacent_room`, `signal`)
and, where applicable, `treatment`. These are authored on the element; there is no separate
module-authoring step.

### `DerivedModule` (resource — read-only, computed by grouping rule)
```json
{
  "id": "HeavyWall[T_ext]",
  "type": "HeavyWall",
  "signal": "T_ext",
  "element_ids": ["e0"]
}
```

Derived modules are returned by `GET /document` and implied by `GET /assembly`. The stable
`id` is `"{type}[{signal}]"` (or just `"{type}"` for signal-less modules like `RoomMass`).
The client never creates, deletes, or routes these — they are server-computed.

### `Signal` (resource — derived from element boundaries)
```json
{
  "id": "s_T_ext",
  "name": "T_ext",
  "kind": "temperature",
  "role": "exterior",
  "meta": {},
  "binding": "open_meteo/temperature_2m"
}
```

`binding` is the optional InfluxDB query string (`measurement/field?tag=val[&tag2=val2]`),
or `null` when unbound.  Identity fields (`id`, `name`, `kind`, `role`, `meta`) are kept
binding-agnostic — grouping never reads `binding`.

Signals are derived by the grouping rule's liveness invariant: they exist when at least one
element's boundary field references them, and are garbage-collected automatically when the
last such element is removed or its boundary field changes.  Signal identity (everything
except `binding`) is read-only — no Signal CRUD endpoints exist.  Bindings are set via
`PUT /models/{id}/signals/{name}/binding`.

### `Problem`
```json
{
  "kind": "double_count",       // "double_count" | "unclaimed_channel" | "missing_room_mass" | "duplicate_state" | "internal_error"
  "message": "Double-count: (element OuterWall, CONDUCTION) already owned by 'DirectLoss'.",
  "cell": ["OuterWall", "CONDUCTION"]   // [element_label, channel_name] or null
}
```

A non-empty `problems` list signals an **engine bug** in the grouping rule, not a user
routing mistake (users no longer route elements).

### `Contribution`
```json
{
  "element_id":    "e0",
  "element_label": "OuterWall",
  "channel":       "CONDUCTION",
  "budget_field":  "UA",
  "value":         3.2
}
```

---

## Registry endpoint

### `GET /api/registry`

Returns the type schemas the frontend uses to render add/edit forms. Element type entries
now include `boundary` and `treatments` so the form knows which boundary fields to render
and whether to show the treatment radio group.

**Response `200`:**
```json
{
  "element_types": [
    {
      "type_name": "OuterWall",
      "fields": [
        {"name": "area",        "type": "float"},
        {"name": "orientation", "type": "enum", "options": ["S","SE","SW","E","W","NE","NW","N"]},
        {"name": "layers",      "type": "list[layer]"},
        {"name": "alpha",       "type": "float", "default": 0.6}
      ],
      "boundary":   {"field": "orientation", "role": "solar+exterior"},
      "treatments": [
        {"key": "thermal_mass", "label": "Thermal-mass wall", "default": true},
        {"key": "simple_loss",  "label": "Simple loss"}
      ]
    },
    {"type_name": "Window",     "fields": [{"name":"area","type":"float"},{"name":"orientation","type":"enum","options":["S","SE","SW","E","W","NE","NW","N"]},{"name":"U","type":"float"},{"name":"shgc","type":"float"}],
     "boundary": {"field": "orientation", "role": "solar+exterior"}, "treatments": []},
    {"type_name": "Floor",      "fields": [{"name":"area","type":"float"},{"name":"boundary","type":"enum","options":["ground","adjacent","exposed"]},{"name":"layers","type":"list[layer]"},{"name":"adjacent_room","type":"str"}],
     "boundary": {"field": "boundary", "role": "varies"}, "treatments": []},
    {"type_name": "Partition",  "fields": [{"name":"area","type":"float"},{"name":"adjacent","type":"str"},{"name":"layers","type":"list[layer]"}],
     "boundary": {"field": "adjacent", "role": "adjacent"}, "treatments": []},
    {"type_name": "IndoorMass", "fields": [{"name":"a","type":"float"},{"name":"b","type":"float"},{"name":"c","type":"float"},{"name":"furniture","type":"enum","options":["bare","normal","heavy"],"default":"normal"}],
     "boundary": null, "treatments": []},
    {"type_name": "HeatSource", "fields": [{"name":"area","type":"float","default":0.0},{"name":"signal","type":"str"}],
     "boundary": {"field": "signal", "role": "prescribed_flux"}, "treatments": []}
  ],
  "module_types": [
    {"type_name": "RoomMass",        "owns": [],                                     "params": ["C_room"],              "fields": []},
    {"type_name": "DirectLoss",      "owns": ["CONDUCTION"],                         "params": ["H_ve"],                "fields": []},
    {"type_name": "SolarGainModule", "owns": ["SOLAR_TRANSMISSION"],                 "params": ["shgcA"],               "fields": []},
    {"type_name": "HeavyWall",       "owns": ["CONDUCTION","STORAGE","SOLAR_OPAQUE"],"params": ["H_out","H_in","C_wall"],"fields": []}
  ],
  "layer_schema": {
    "fields": [
      {"name": "material", "type": "enum", "options": ["concrete", "brick", "wood", "glass_wool", "steel", "air"]},
      {"name": "thickness", "type": "float"}
    ]
  }
}
```

---

## Document endpoint

### `GET /api/models/{id}/document`

Returns the raw room document: authored elements, plus derived read-only modules and signals
computed by the grouping rule.

**Response `200`:**
```json
{
  "model_id": "default",
  "elements": [<Element>, …],
  "modules":  [<DerivedModule>, …],
  "signals":  [<Signal>, …]
}
```

`modules` and `signals` are derived (read-only) — they are computed from `elements` by the
grouping rule on every request. `doc.modules` / `doc.routes` in the persisted JSON are
vestigial load-compatibility fields only; the server never writes to them.

---

## Element CRUD

The sole mutating authoring surface. After any element mutation the frontend re-fetches
`/document` **and** `/assembly` to refresh all derived views.

### `POST /api/models/{id}/elements`

Add an element.

**Request body:**
```json
{"type": "OuterWall", "fields": {"area": 10.0, "orientation": "S", "layers": [{"material": "concrete", "thickness": 0.2}], "alpha": 0.6}}
```

Include boundary and treatment fields in `fields` as appropriate:
- `OuterWall` / `Window`: `"orientation": "S"` (enum); `OuterWall` may also carry `"treatment": "thermal_mass"`.
- `Floor`: `"boundary": "adjacent"` + `"adjacent_room": "kitchen"` (when adjacent).
- `Partition`: `"adjacent": "kitchen"`.
- `HeatSource`: `"signal": "hvac"` (creates boundary signal `Q_hvac`).
- `IndoorMass`: no boundary field; auto-paired to derived `RoomMass`.

**Response `201`:** `<Element>` (with server-assigned `id` and computed `budgets`)

---

### `PATCH /api/models/{id}/elements/{eid}`

Update an element's fields (partial update — only provided fields are changed). A boundary
field edit may auto-create or garbage-collect `Signal` resources as a side effect; the
re-pull invariant refreshes the derived signal list and modules.

**Request body:**
```json
{"fields": {"area": 12.0}}
```

**Response `200`:** `<Element>` (updated, with recomputed `budgets`)

---

### `DELETE /api/models/{id}/elements/{eid}`

**Response `204`** (no body). Signal GC happens at read time (liveness invariant in the
grouping rule); no routing cleanup is needed because modules are derived, not stored.

---

---

## InfluxDB signal-binding

### `GET /api/influx/signals`

List all queryable signal names from the connected InfluxDB instance.

**Response `200`:** `["open_meteo/temperature_2m", "daikin_aircon/inside_temperature?mac=…&name=Salon&type=aircon", …]`

Signal names follow the format `measurement/field?tag=val[&tag2=val2]`.

**Response `503`:** `{"detail": "InfluxDB unreachable: …"}` when the DB is not reachable.

---

### `PUT /api/models/{id}/signals/{signal_name}/binding`

Set or clear the InfluxDB binding for the named signal.

`signal_name` must be a derived required signal for the model (e.g. `T_ext`, `G_sol_S`); returns
`404` if not found.

**Request body:**
```json
{"binding": "open_meteo/temperature_2m"}
```
Use `{"binding": null}` to clear a previously set binding.

**Response `200`:** `<Signal>` (the updated SignalOut with `binding` populated or `null`).

**Response `400`:** Malformed binding string (must parse as `measurement/field[?tag=val]`).

**Response `404`:** `signal_name` is not a required signal for this model.

---

### `POST /api/models/{id}/simulate-bound`

Run the forward simulation by fetching real InfluxDB data for each bound required signal.
All required signals must be bound; unbound signals are rejected with a descriptive 400.

**Request body:**
```json
{
  "start":    "2026-05-25T00:00:00Z",
  "end":      "2026-05-27T00:00:00Z",
  "resample": "15min",
  "x0":       [20.0, 20.0],
  "params":   {"H_ve": 3.2}
}
```

`start` / `end` are ISO-8601 strings (timezone-naive strings are treated as UTC).  `resample`
is a pandas offset string (default `"15min"`).  `x0` and `params` follow the same conventions
as `POST /simulate`; both are optional.  The time step `dt` is inferred from `resample`.

**Response `200`:** same shape as `POST /simulate`:
```json
{"t": [0.0, 900.0, …], "states": {"T_room": [20.0, …]}}
```

**Response `400`:** Incomplete room, unbound required signals, or empty/NaN series.

**Response `503`:** InfluxDB unreachable during fetch.

---

## Retired endpoints

The following endpoints were removed in D3. They return **404** (no matching route):

| Endpoint | Reason |
|----------|--------|
| `POST /api/models/{id}/modules` | Modules are derived, not authored. |
| `DELETE /api/models/{id}/modules/{mid}` | Modules are derived, not authored. |
| `PUT /api/models/{id}/modules/{mid}/routing` | Routing is determined by element boundary fields, not a routing table. |

---

## Assembly projection (the heart)

### `GET /api/models/{id}/assembly`

Rebuilds the system via the non-raising assembler path (`strict=False`) and returns all
derived views. **Never 500s.**

**Response `200`:**
```json
{
  "ownership": [
    {
      "element_id":    "e0",
      "element_label": "OuterWall",
      "channel":       "CONDUCTION",
      "module_id":     "HeavyWall[T_ext]"
    }
  ],
  "parameters": [
    {
      "name":    "H_ve",
      "module_id": "DirectLoss[T_ext]",
      "prior":   {"mu_log": 1.2, "sigma_log": 0.47},
      "contributions": [
        {
          "element_id":    "e0",
          "element_label": "OuterWall",
          "channel":       "CONDUCTION",
          "budget_field":  "UA",
          "value":         3.2
        }
      ]
    }
  ],
  "states":  ["T_wall", "T_room"],
  "signals": ["T_ext", "G_sol_S"],
  "required_signals": [
    {"id": "s_T_ext",   "name": "T_ext",   "kind": "temperature", "role": "exterior",    "meta": {}},
    {"id": "s_G_sol_S", "name": "G_sol_S", "kind": "irradiance",  "role": "solar",       "meta": {"orientation": "S"}}
  ],
  "graph": {
    "nodes": [
      {"id": "T_room",  "kind": "room"},
      {"id": "T_wall",  "kind": "state"},
      {"id": "T_ext",   "kind": "boundary"},
      {"id": "G_sol_S", "kind": "boundary"}
    ],
    "edges": [
      {"from": "T_ext",  "to": "T_room", "module_id": "DirectLoss[T_ext]"},
      {"from": "T_wall", "to": "T_room", "module_id": "HeavyWall[T_ext]"}
    ]
  },
  "problems": []
}
```

*`problems` is empty `[]` when the room is valid. A non-empty `problems` list indicates an
**engine bug** in the grouping rule (not a user mistake). `ownership`, `parameters`,
`states`, `signals`, `required_signals`, `graph` may be partial when problems exist.*

`required_signals` is the input list the right-column "Required signals" panel renders:
the set of `Signal`s the derived modules demand, each with `role`/`kind`/`meta` so the UI
knows what series to ask for. It is always derived from the grouping result, even when
`system` is `None` (problems exist).

---

## Physics views

### `POST /api/models/{id}/simulate`

Run the forward simulation. Signals and params are provided in the request body.

**Request body:**
```json
{
  "signals": {
    "T_ext":   [20.0, 20.1, 19.8, …],
    "G_sol_S": [0.0, 50.0, 120.0, …]
  },
  "x0":    [18.0, 18.0],
  "params": {"H_ve": 3.2, "C_room": 150000.0},
  "dt":    3600.0
}
```

`signals` keys are the `Signal.name`s from `assembly.required_signals` (e.g. `T_ext`,
`G_sol_S`, `T_kitchen`, `Q_hvac`). `params` is optional — omitted fields use prior means.
`dt` defaults to `3600.0` s.

**Response `200`:**
```json
{
  "t":      [0.0, 3600.0, 7200.0, …],
  "states": {
    "T_wall": [18.0, 18.3, 18.6, …],
    "T_room": [18.0, 18.5, 19.1, …]
  }
}
```

---

### `GET /api/models/{id}/identifiability`

Run the identifiability lens (Step 1 engine) at prior-mean parameters. Returns a pre-fit verdict per parameter.

**Query params (all optional):**
- `signals` — not applicable for GET; use `POST /identifiability` if signal arrays are needed later. For now the endpoint uses a default 7-day synthetic diurnal signal when none is stored.

**Response `200`:**
```json
{
  "param_status": {
    "H_ve":   {"status": "resolvable",      "reason": "non-constant boundary signal, low collinearity", "tau_h": 2.1,  "correlation": 0.12},
    "C_wall": {"status": "borderline",      "reason": "high collinearity between T_ext and G_sol",      "tau_h": 18.4, "correlation": 0.84},
    "shgcA":  {"status": "prior_dominated", "reason": "boundary signal is constant",                     "tau_h": 2.1,  "correlation": null}
  }
}
```

`status` ∈ `{"resolvable", "borderline", "prior_dominated"}`.  
`tau_h` is the pole time-constant in hours.  
`correlation` is the max pairwise Pearson r among non-constant boundary signals (null when not applicable).

---

### `GET /api/models/{id}/topology.svg`

Returns the star-topology schematic as an SVG image (server-side schemdraw/matplotlib render).

**Response `200`:**  
`Content-Type: image/svg+xml`  
Body: SVG text.

---

## Error responses

| Status | When |
|--------|------|
| `400`  | Invalid request body (wrong type, missing required field) |
| `404`  | Unknown `model_id`, `element_id`, or retired endpoint |
| `422`  | Pydantic validation error (field value out of range, bad enum) |
| `500`  | Unexpected server error (should not happen for `/assembly`) |

All errors return:
```json
{"detail": "human-readable message"}
```
