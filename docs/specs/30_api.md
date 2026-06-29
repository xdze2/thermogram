# 30 — API Contract (FastAPI ↔ Svelte)

**Status: FROZEN.** Track B (FastAPI) and Track F (Svelte) code against this. Any change
must be made **here first**; both sides then adapt together. This is the single source of
truth for endpoint shapes — it sits *under* the specs umbrella (see
[`00_overview.md`](00_overview.md)) but its freeze discipline is unchanged from when it
lived at `docs/api_contract.md`.

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
  "fields": [<FieldSchema>, …]
}
```

### `ModuleTypeSchema`
```json
{
  "type_name": "RoomMass",
  "owns": [],               // list of Channel names this module claims
  "params": ["C_room"],
  "fields": [<FieldSchema>, …]
}
```

> **`owns` is the channel-compatibility source for the routing UI.** It is already part of
> this payload. The frontend routing controls must filter on it (`m.owns ∩ element channels`,
> see [`20_layout.md`](20_layout.md)). No backend change is needed for that fix.

### `Element` (resource)
```json
{
  "id": "e0",
  "type": "OuterWall",
  "label": "OuterWall",
  "fields": {"area": 10.0, "orientation": "S", "layers": [{"material": "concrete", "thickness": 0.2}], "alpha": 0.6},
  "budgets": {
    "CONDUCTION":        {"UA": 3.2, "shgcA": null, "alphaA": null, "C": null},
    "SOLAR_OPAQUE":      {"UA": null, "shgcA": null, "alphaA": 6.0, "C": null},
    "STORAGE":           {"UA": null, "shgcA": null, "alphaA": null, "C": 52000.0}
  }
}
```

### `Module` (resource)
```json
{
  "id": "m0",
  "type": "HeavyWall",
  "element_ids": ["e0"]
}
```

### `Problem`
```json
{
  "kind": "double_count",       // "double_count" | "unclaimed_channel" | "missing_room_mass" | "duplicate_state"
  "message": "Double-count: (element OuterWall, CONDUCTION) already owned by 'DirectLoss'.",
  "cell": ["OuterWall", "CONDUCTION"]   // [element_label, channel_name] or null
}
```

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

Returns the type schemas the frontend uses to render add/edit forms.

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
      ]
    },
    {"type_name": "Window",     "fields": [{"name":"area","type":"float"},{"name":"orientation","type":"enum","options":["S","SE","SW","E","W","NE","NW","N"]},{"name":"U","type":"float"},{"name":"shgc","type":"float"}]},
    {"type_name": "Floor",      "fields": [{"name":"area","type":"float"},{"name":"boundary","type":"enum","options":["ground","adjacent","exposed"]},{"name":"layers","type":"list[layer]"}]},
    {"type_name": "Partition",  "fields": [{"name":"area","type":"float"},{"name":"layers","type":"list[layer]"}]},
    {"type_name": "IndoorMass", "fields": [{"name":"area","type":"float","default":0.0},{"name":"C","type":"float"}]},
    {"type_name": "HeatSource", "fields": [{"name":"area","type":"float","default":0.0}]}
  ],
  "module_types": [
    {"type_name": "RoomMass",       "owns": [],                                    "params": ["C_room"],             "fields": [{"name":"floor_area","type":"float"}]},
    {"type_name": "DirectLoss",     "owns": ["CONDUCTION"],                        "params": ["H_ve"],               "fields": []},
    {"type_name": "SolarGainModule","owns": ["SOLAR_TRANSMISSION"],                "params": ["shgcA"],              "fields": []},
    {"type_name": "HeavyWall",      "owns": ["CONDUCTION","STORAGE","SOLAR_OPAQUE"],"params": ["H_out","H_in","C_wall"],"fields": []}
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

Returns the raw room document (elements, modules, routing) without projection.

**Response `200`:**
```json
{
  "model_id": "default",
  "elements": [<Element>, …],
  "modules":  [<Module>, …]
}
```

---

## Element CRUD

### `POST /api/models/{id}/elements`

Add an element.

**Request body:**
```json
{"type": "OuterWall", "fields": {"area": 10.0, "orientation": "S", "layers": [{"material": "concrete", "thickness": 0.2}], "alpha": 0.6}}
```

**Response `201`:** `<Element>` (with server-assigned `id` and computed `budgets`)

---

### `PATCH /api/models/{id}/elements/{eid}`

Update an element's fields (partial update — only provided fields are changed).

**Request body:**
```json
{"fields": {"area": 12.0}}
```

**Response `200`:** `<Element>` (updated, with recomputed `budgets`)

---

### `DELETE /api/models/{id}/elements/{eid}`

**Response `204`** (no body). Also removes this element from any module's routing.

---

## Module CRUD

### `POST /api/models/{id}/modules`

Add a module.

**Request body:**
```json
{"type": "HeavyWall", "fields": {}}
```
For `RoomMass`: `{"type": "RoomMass", "fields": {"floor_area": 20.0}}`

**Response `201`:** `<Module>`

---

### `DELETE /api/models/{id}/modules/{mid}`

**Response `204`** (no body).

---

### `PUT /api/models/{id}/modules/{mid}/routing`

Set which elements are routed to this module (replaces the full list).

**Request body:**
```json
{"element_ids": ["e0", "e1"]}
```

**Response `200`:** `<Module>` (updated)

---

## Assembly projection (the heart)

### `GET /api/models/{id}/assembly`

Rebuilds the system via the non-raising assembler path (`strict=False`) and returns all derived views. **Never 500s.**

**Response `200`:**
```json
{
  "ownership": [
    {
      "element_id":    "e0",
      "element_label": "OuterWall",
      "channel":       "CONDUCTION",
      "module_id":     "m1"
    }
  ],
  "parameters": [
    {
      "name":    "H_ve",
      "module_id": "m1",
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
  "signals": ["T_ext", "G_sol"],
  "graph": {
    "nodes": [
      {"id": "T_room",  "kind": "room"},
      {"id": "T_wall",  "kind": "state"},
      {"id": "T_ext",   "kind": "boundary"},
      {"id": "G_sol",   "kind": "boundary"}
    ],
    "edges": [
      {"from": "T_ext",  "to": "T_room", "module_id": "m1"},
      {"from": "T_wall", "to": "T_room", "module_id": "m2"}
    ]
  },
  "problems": [
    {
      "kind":    "double_count",
      "message": "Double-count: (element OuterWall, CONDUCTION) already owned by 'DirectLoss'.",
      "cell":    ["OuterWall", "CONDUCTION"]
    }
  ]
}
```

*`problems` is empty `[]` when the room is valid. `ownership`, `parameters`, `states`, `signals`, `graph` may be partial when problems exist.*

---

## Physics views

### `POST /api/models/{id}/simulate`

Run the forward simulation. Signals and params are provided in the request body.

**Request body:**
```json
{
  "signals": {
    "T_ext": [20.0, 20.1, 19.8, …],
    "G_sol": [0.0, 50.0, 120.0, …]
  },
  "x0":    [18.0, 18.0],
  "params": {"H_ve": 3.2, "C_room": 150000.0},
  "dt":    3600.0
}
```
`params` is optional — omitted fields use prior means. `dt` defaults to `3600.0` s.

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
| `404`  | Unknown `model_id`, `element_id`, or `module_id` |
| `422`  | Pydantic validation error (field value out of range, bad enum) |
| `500`  | Unexpected server error (should not happen for `/assembly`) |

All errors return:
```json
{"detail": "human-readable message"}
```
