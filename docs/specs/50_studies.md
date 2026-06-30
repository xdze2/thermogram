# 50 — Studies

**Status: TARGET.** Not yet built. This spec defines the Study concept and its API; no
implementation exists. When code is written, it must satisfy this spec.

---

## What a Study is

A **Study** is a run configuration attached to a model. It bundles:

- a **time window** (`start`, `end`, `resample`)
- optional **signal-binding overrides** (per-signal, layered over the model-level defaults)
- optional **parameter overrides** (for manual forward runs)
- **results** (simulation output, fit posteriors) — null until the study is run

One model can have many Studies. The model (elements, grouping, priors) is the expensive thing
to author; a Study is cheap to create and disposable. A user will want to try the same room
over different time windows, compare "with HVAC signal" vs "without", or archive a fit result
for a specific period without losing it on the next run.

Studies are **not** a replacement for model-level signal bindings. The model always has its
own binding defaults (set via `PUT /models/{id}/signals/{name}/binding`); a Study can
snapshot and override them for a specific run, but the model's defaults persist independently.

---

## The Study resource

```jsonc
{
  "uid":        "study_abc123",          // server-assigned, stable
  "model_uid":  "model_xyz",             // FK — the owning model
  "name":       "June heat wave",        // mutable user label
  "created_at": "2026-06-30T10:00:00Z",
  "updated_at": "2026-06-30T14:32:00Z",

  // --- run configuration ---
  "time_range": {
    "start":    "2026-06-17T00:00:00Z",
    "end":      "2026-06-25T00:00:00Z",
    "resample": "15min"                  // pandas offset string; default "15min"
  },

  // signal bindings: null means "inherit from model"; a string overrides
  // keys are Signal names (e.g. "T_ext", "G_sol_S"); only overridden signals appear here
  "signal_overrides": {
    "T_ext": "open_meteo/temperature_2m"
  },

  // parameter overrides for forward simulation; null means "use prior means"
  "params": {
    "H_ve": 3.2
  },

  // --- results (null until the study is run) ---
  "results": {
    "simulate": {
      "ran_at": "2026-06-30T14:32:00Z",
      "t":      [0.0, 900.0, 1800.0, "…"],
      "states": {
        "T_room": [20.0, 20.1, "…"],
        "T_wall": [19.8, 19.9, "…"]
      }
    },
    "fit": null                          // reserved for Step 2–3; shape TBD
  }
}
```

`results` is the only field the server writes on a run; all other fields are author-controlled
and only change on explicit PATCH.

---

## Signal-binding resolution

When a Study is run, the **effective binding** for each required signal is resolved in order:

1. `study.signal_overrides[signal_name]` — if present and non-null, use it.
2. `model.signals[signal_name].binding` — the model-level default.
3. If both are null, the run is rejected with `400 Unbound signal`.

This means:
- A Study does not need to specify every binding — it only overrides what differs from the
  model's defaults.
- Changing the model's bindings after a Study is created does not retroactively alter a Study
  that has an explicit override for that signal.
- A Study with no `signal_overrides` at all inherits the full model binding snapshot at run
  time (not at creation time — it re-reads the model's current bindings on each run).

---

## Persistence

Studies are persisted alongside their model in `user_data/{model_uid}.json`, under a
`"studies"` key. The Study UID is stable across renames and re-runs. Deleting a model deletes
all its Studies.

```jsonc
// user_data/{model_uid}.json (extended shape)
{
  "model_id": "model_xyz",
  "name":     "My room",
  "elements": ["…"],
  "signals":  ["…"],
  "studies": {
    "study_abc123": { "…Study fields sans model_uid…" }
  }
}
```

---

## API

All Study endpoints are scoped under the owning model.

### List

```
GET /api/models/{model_id}/studies
```

**Response `200`:** array of Study objects (full shape including `results`), ordered by
`created_at` ascending.

---

### Create

```
POST /api/models/{model_id}/studies
```

**Request body** (all fields optional at creation):
```json
{
  "name":             "June heat wave",
  "time_range":       {"start": "2026-06-17T00:00:00Z", "end": "2026-06-25T00:00:00Z", "resample": "15min"},
  "signal_overrides": {},
  "params":           {}
}
```

`name` defaults to `"Untitled study"`. `time_range` defaults to null (must be set before
running). `signal_overrides` and `params` default to `{}`.

**Response `201`:** the created Study (with server-assigned `uid`, null `results`).

---

### Get

```
GET /api/models/{model_id}/studies/{study_id}
```

**Response `200`:** full Study object.  
**Response `404`:** unknown `model_id` or `study_id`.

---

### Update (patch)

```
PATCH /api/models/{model_id}/studies/{study_id}
```

Updates any author-controlled fields. Does **not** touch `results` — results are only written
by a run endpoint.

**Request body** (partial — only provided fields are changed):
```json
{
  "name":             "June heat wave v2",
  "time_range":       {"start": "2026-06-17T00:00:00Z", "end": "2026-06-30T00:00:00Z"},
  "signal_overrides": {"T_ext": "open_meteo/temperature_2m"},
  "params":           {"H_ve": 3.2}
}
```

`time_range` is merged field-by-field (only provided sub-fields are changed).

Patching `signal_overrides` or `params` replaces the entire object (not a nested merge).
Set a key to `null` to revert it to the inherited default.

Patching any configuration field does **not** clear `results` automatically — the client
decides whether to clear them (via `DELETE …/results`) or keep the stale results visible.

**Response `200`:** the updated Study.  
**Response `404`:** unknown study.

---

### Delete

```
DELETE /api/models/{model_id}/studies/{study_id}
```

**Response `204`.**  
**Response `404`:** unknown study.

---

### Clear results

```
DELETE /api/models/{model_id}/studies/{study_id}/results
```

Clears `results.simulate` and `results.fit` (sets both to null). Configuration fields are
unchanged.

**Response `200`:** the updated Study (with null results).

---

### Run simulation

```
POST /api/models/{model_id}/studies/{study_id}/run/simulate
```

Resolves the effective signal bindings (override → model default), fetches InfluxDB data for
the study's `time_range`, runs the forward simulation, and writes the result into
`results.simulate`. `results.fit` is untouched.

**Request body:** empty `{}`, or optionally:
```json
{"x0": [20.0, 20.0]}
```

`x0` defaults to all-20 °C if omitted. Parameters come from `study.params` (merged with
prior means for any unspecified parameter).

**Response `200`:** the full Study object with `results.simulate` populated.

**Response `400`:**
- `time_range` is null (not set)
- one or more required signals have no effective binding
- InfluxDB returned empty or NaN series

**Response `503`:** InfluxDB unreachable.

---

## Relationship to existing endpoints

The pre-Study `POST /simulate-bound` endpoint stays for quick one-off runs from the UI
without creating a Study. Studies are the persistence layer on top of it.

The fit endpoints (`POST …/fit`, Step 2–3) will write into `results.fit`; their shape is
reserved (`null` for now) and will be specified in a future `55_fit.md`.

---

## Frontend state

Studies are a **separate data layer** from the model document. They do not participate in
the `applyMutation` → re-pull `document`+`assembly` invariant (spec `10_state.md`). The
frontend maintains a separate `studies` store:

```js
// stores/studies.js
studies      // writable — array of Study for the current model
activeStudy  // writable — the currently open Study (null if none)
```

Study mutations (create, patch, delete, run) update `studies` and `activeStudy` in place;
they do not re-pull `document` or `assembly`. Entering a model editor re-fetches studies
alongside `document`+`assembly` in the initial `refreshAll`.
