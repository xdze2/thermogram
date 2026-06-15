# thermogram — todo: road to v1

For architecture see [project_description.md](project_description.md).
The target design is [modeling_pipeline.md](modeling_pipeline.md); v1
implements its **lumped model layer (the φ-space)** in minimal form. The beliefs /
domain / agent layers and the SystemTemplate hot-path of
[implementation.md](implementation.md) remain post-v1.

---

## What v1 is

A minimal working app demonstrating the key value:

> Describe your house in physical terms, point the app at measured
> temperature data, press Fit — and read off the thermal properties of the
> building (wall R / λ, capacitance) **with uncertainty**, mapped back onto
> the building elements you described.

The enabler is the **lumped model layer**: the fit no longer patches atomic node
fields directly (today's `fit_config["params"]` + `_patch_model` label-hack)
but operates on a φ-vector of lumped elements (`Req`, `Ceq`, `RC_chain`, `T_boundary`,
`Q_source`) expanded to atoms via combine rules. This is what makes the
parameter choice clean, the fit identifiable by construction, and the
mapping back to elements well-defined.

Acceptance scenario (the "v1 demo"):

1. Fresh clone, `uv sync`, `npm run build`, start the server. **No InfluxDB,
   no env vars.**
2. Open the bundled example house. It has one fit study pre-configured
   against a bundled example dataset.
3. The study's φ-table shows a handful of lumped elements with physically composed
   priors. Press Fit. It converges with default settings.
4. The result reads as element-level properties: `Mur SE: U = 1.4 ± 0.3`
   (posterior vs prior visible), plus residual charts that look unstructured.
5. Total time for a newcomer following the README: under 10 minutes.

Steps are ordered; each is independently testable and leaves the app working.

---

## Step 0 — Green baseline ✅

- [x] Add a `dev` dependency group to `pyproject.toml` (`pytest`).
- [x] Recreate the test fixtures (`chambre_1r1c.json`, `chambre_2r2c.json`,
      `chambre_v1.json`) as **committed files** under
      `thermogram/solver/tests/fixtures/` — test data lives with the tests,
      not in the mutable `data/` dir.
- [x] Point `test_physics.py` at a committed fixture copy of `maison_test`,
      never at live user data.
- [x] Fix whatever still fails after that (no pre-existing failures remained
      once fixtures were in place — 62/62 green).

**Test:** `uv run pytest` is green on a fresh clone, and stays green after
the user edits any house in `data/houses/`.

---

## Step 1 — Synthetic round-trip on the current fit path ✅

The scientific core as one automated test — and the safety net for the
lumped-model refactor that follows.

- [x] Script/test: take a small example house (1 room, 1 chained wall,
      outdoor boundary), `expand()`, simulate forward with **known**
      ground-truth params and synthetic weather (sinusoid + noise) →
      synthetic "measured" indoor temperature.
- [x] Perturb priors away from ground truth (×2 on R, ×0.5 on C), run
      `fit_nls` on the synthetic observations.
- [x] Assert recovery: fitted `R_wall`, `C_wall` within tolerance (10 %);
      reported σ consistent with the injected noise.
- [x] Keep as a pytest (mark `roundtrip`).

**Test:** `uv run pytest -m roundtrip` recovers ground-truth parameters
through the *current* fit path.

---

## Step 1.2 — Pydantic models as the single data contract ✅

Today nothing structurally defines the core types: the house, study, and
atomic model cross the API as untyped `dict`, and the only real typing was
three `*Request` envelopes in `api/main.py`. The hand-written JSON Schemas
under `schema/` described those shapes but validated nowhere and had drifted
(`solar_absorptance` vs `alpha_solar`, missing `studies` / `solar_signal` /
room `role`, `schema_version` "0.2" vs the live "0.3"). They have been
**dropped** in favour of Pydantic models.

- [x] `thermogram/models.py` — canonical models for all three layers:
      domain/element (`House`, `Room`, the discriminated `Element` union,
      `Material`/`MaterialEntry`, `Study`), atomic (`AtomicModel` with the
      mass/boundary/resistance/source node union + `Edge`), and the lumped
      φ-space (`LumpedElement`, `View`, `Prior`, `Posterior`) — the last
      defined but **not yet wired** (it is the Step 2/3 contract).
- [x] Modelled against what the code + real files actually use (not the old
      schemas); `tests/test_models.py` pins them to every house / fixture /
      material file and to live `expand()` output so they can't drift.
- [x] Deleted `schema/*.json` and the dead `$schema` refs in
      `data/materials/*.json`.
- [x] Wire the API routes to the models instead of bare `dict`: `get_house`
      / `put_house` / `create_house`, `create_study` / `put_study` /
      `get_study`, and `post_house_expand` validate in/out against `House`,
      `Study`, `AtomicModel`. FastAPI validates request bodies and generates
      the OpenAPI schema (served at `/docs`) for free.
- [x] `PreviewGroupsRequest.atomic_model` typed as `AtomicModel` (was
      `dict`). `SimulateRequest` and `FitRequest` keep `params: dict[str, dict]`
      — superseded by the view work in Step 3.
- [x] Boundary convention: routes accept/return models; the solver keeps
      reading plain dicts. `expand()` and friends are fed via
      `house.model_dump(by_alias=True, exclude_none=True)` and their output
      re-validated as `AtomicModel`. Computed `_model_hash` / `_stale_*`
      fields work via `extra="allow"`.
- [x] `tests/test_api.py` — API-level tests (92/92 green): malformed body →
      422; valid PUT→GET round-trip preserves all fields; expand returns a
      valid `AtomicModel`; study CRUD.
- [x] "API docs ↗" link in the UI nav (→ `/docs`, FastAPI Swagger UI).

Deferred to Step 4:
- [ ] Generate the frontend's TypeScript types from the OpenAPI schema so
      `ui/` stops passing implicit `any`.

**Test:** `uv run pytest` is green (92/92). A malformed house/study POST/PUT
returns 422; a valid round-trip preserves every field; `/houses/{name}/expand`
returns a payload that validates as `AtomicModel`.

---

## Step 2 — Lumped model layer in the solver (φ-space) ✅

Minimal version of the lumped model layer from modeling_pipeline.md. Scope cuts
to keep it v1-sized:

- **Atoms = current `atomic_model` nodes.** No rewrite of `physics.py`; lumped
  elements overlay the existing `expand()` output, referencing atomic node ids.
- **No Belief objects.** Priors are `(nominal, sigma_log)` pairs composed at
  view-build time from element data (materials, geometry).
- **No transform ops** (refine/coarsen/tie) and no agent — only `free` /
  `fixed` modes on each lumped element.

- [x] `solver/lumps.py` — five combine rules as pure functions (`series_sum`,
      `parallel_sum`, `parallel_inv_sum`, `chain`, `identity`), `expand_lumped`
      dispatcher, `apply_atom_values` (deep-copy patcher), prior composition
      helpers, and `ChainAtoms` dataclass. φ = prior ⇒ atoms = their nominals.
- [x] `solver/view.py` — `build_default_view(atomic_model, expansion_map) → View`,
      deterministic, one depth:
      - opaque with mass → one `RC_chain` lump; Rse/Rsi in `lump.atoms`
        (provenance) but excluded from `ChainAtoms.r_atom_ids` — fixed share,
        not free φ (kills today's series-identifiability trap structurally);
      - opaque no_mass → `Req` (series_sum);
      - glazing / air_exchange → `Req`; parallel R between same node pair →
        one shared `Req` (`parallel_inv_sum`), replacing `group_params`;
      - room → `Ceq`; boundaries / sources → `identity`, mode `fixed`.
      Also exports `chain_atoms_for_lump` and `get_chain_priors`.
- [x] `solver/fit.py` — added `build_forward_from_view` + `fit_nls_view` +
      `ViewFitResult`. Residual closure maps log-φ → atom values (via combine
      rules) → `apply_atom_values` → `assemble` → `simulate_zoh`. Posteriors
      keyed by lumped element id (`lump_id + "_R"` / `"_C"` for chains). Legacy
      `build_forward` / `_patch_model` kept for the API until Step 3.

Implementation note: φ_R for an RC_chain is the **sum of interior R-node
nominals** (not `R_wall` from `wall_chains`), because `expand()` creates N−1
interior R nodes at `R_wall/N` each. This makes φ = prior reproduce the
original atomic model exactly.

**Test:** `uv run pytest` is green (140/140). Unit tests per combine rule in
`test_lumps.py` (29 tests); `build_default_view` on all fixture houses in
`test_view.py` (18 tests) — coverage, Rse/Rsi folding, chain prior positivity.
`test_roundtrip_phi_path` (marked `roundtrip`) recovers ground-truth R and C
through the φ path; legacy `test_roundtrip_wall_R_and_C` kept as regression guard.

---

## Step 3 — Data model + API adaptation ✅

The study persists the View; results are posteriors on lumped elements.

- [x] Study schema: `Study.view` (already defined in `models.py`) is now
      wired — the persisted view carries lumped elements (id, kind, atom ids,
      combine, prior, mode) and per-lump posteriors written back after fit.
      Old `fit.params` / `fit.method` config dropped (no migration — files
      recreated from scratch).
- [x] `model_hash` staleness extends to the view: the view stores its build
      hash; `_stale_view` flag injected on every study GET; `/fit/run` rejects
      (409) when stale.
- [x] API:
      - `POST /houses/{name}/studies/{id}/view` — (re)build the default
        view, persist it, return it with `_stale_view: false`;
      - `GET .../view` — current view with stale flag;
      - `PUT .../view` — update modes / prior overrides only (topology is
        always the default build for v1);
      - `/fit/run` takes the persisted view; rejects 400 if missing, 409 if stale.
- [x] `/fit/preview-groups` removed (subsumed by the view).

**Test:** 148/148 green. API-level tests: create study → build view → flip a
lumped element to `fixed` → stale detection after house edit → fit rejected
when view missing or stale → `preview-groups` returns 404.

---

## Step 4 — UI adaptation: FitPanel becomes the φ-table ✅

- [x] FitPanel rewritten as the φ-space table, one row per lumped element:
      label (from realizing element), kind badge, prior (nominal ± σ_log),
      mode toggle (free/fixed), posterior ± σ after fit,
      prior→posterior shift indicator.
- [x] Remove the node-field param table and its grouping preview UI.
- [x] "Rebuild view" button when the study is stale (calls `POST .../view`).
- [x] Post-fit forward sim uses fitted `atomic_model` returned by `/fit/run`
      (via `param_overrides`) instead of the old node-field patches.

**Test:** manual UI pass on a fixture house — build view, freeze a lumped element,
fit, see posteriors in the table; stale → rebuild flow works.

---

## Step 4.2 — Fit panel polish and usability fixes

Issues surfaced during first real use of the Step 4 UI:

- [x] **Human-readable lump labels**: `build_default_view` now takes an
      optional `element_labels` map (built in `post_study_view` from rooms +
      elements) and resolves `lump.label` from it, falling back to a cleaned
      atom label (strips the `(Rsi)`/`[inner]` suffixes) then the lump id.
- [x] **RC_chain: one row, two columns** — the φ-table iterates one row per
      lump with Nominal R / Nominal C in their own columns (verified on the
      `maison_test` chain).
- [x] **Rename "view" → "lumped model"** in the panel headers/buttons
      (`FitPanel.svelte`). API routes unchanged.
- [x] **Merge run + fit into one panel**: `study.type` no longer gates the UI.
      `SimulationRun.svelte` retired; its charts extracted to the shared
      `SimCharts.svelte`. The single study panel (`FitPanel.svelte`) shows the
      φ-table with "Run forward" alongside "Run fit"; forward uses the
      nominals (with overrides), fit overwrites with posteriors and re-runs the
      forward sim from the fitted model. One "+ New study" button.
- [x] **Manual parameter override**: editable nominal `<input>` per lump row
      (active when mode ≠ fixed), debounced, persisted via `PUT .../view`
      (`prior.nominal` / `prior_C.nominal`).
- [x] **Fit y₀ (initial state)**: `fit_y0: bool` on `FitRequest`. When true,
      `build_forward_from_view` appends one **linear** scalar to the parameter
      vector (key `"y0"`, kept out of the φ-space), broadcast uniformly over
      the mass nodes in the forward closure; `fit_nls_view` returns
      `phi_fitted["y0"]` and the API surfaces it as `fitted_y0`. Covered by
      `test_roundtrip_phi_path_with_fit_y0`.
- [ ] **Lumped-model graph**: a small SVG/canvas view of the lumped RC network
      (one node per lump, edges from the `atoms` connectivity) shown alongside
      the φ-table, so the user can see what they are fitting. Can reuse the
      existing `GraphView` filtered to lumped-node granularity, or be a
      dedicated lightweight component.
- [ ] **Prior sanity**: verify that `build_default_view` produces priors close
      enough to reality that NLS converges from them on a typical house. Check
      against the Step 1 round-trip test; tighten or widen σ_log as needed.

**Test:** the Step 1 round-trip (`uv run pytest -m roundtrip`) still passes
after any solver changes. Manual UI pass: labels are human-readable, RC_chain
is one row, forward run + fit work from the same panel, y₀ is fitted.

---

## Step 5 — CSV data source: drop the InfluxDB requirement

Independent of Steps 2–4; can be done in parallel.

- [ ] Extract a minimal datasource interface from `api/influx.py`:
      `list_signals()` and `get_series(signal, start, end)`.
- [ ] CSV source: `data/datasets/*.csv` (first column timestamp). Signal
      naming: `csv/<file>/<column>`.
- [ ] `GET /signals` merges sources; `GET /series` dispatches on prefix.
      Influx registered only when `MINIHA_INFLUX_*` env vars are set.
- [ ] No upload UI for v1 — dropping a file into `data/datasets/` is
      enough (document it).

**Test:** with no Influx env vars, the API starts, `GET /signals` lists CSV
columns, a study wired to CSV signals runs end-to-end. Unit tests for
parsing, 15-min resampling, range slicing.

---

## Step 5.5 — Input data validation layer

Motivated by a real bug: a unit error in the Influx timestamp conversion
(`datetime64[us]` under pandas 3.0 cast as if it were `[ns]`) put the
boundary signal ~56 years before the simulation window. Every grid point
fell outside the signal range, `interp1d` clamped to a constant, and the
forward sim flat-lined regardless of R, C, or solver. **It produced a
plausible-looking wrong answer with no error.** `fetch_series` returning an
empty Series on a missing signal is a second silent path to the same place.

A validation layer between data fetch and the solver that rejects unusable
inputs loudly, instead of letting them degrade into a constant.

- [ ] Validate each fetched input/observation series before it reaches the
      solver. Main criterion: **at least one point per hour** over the
      requested `[start, end)` window (no gap longer than 1 h, and the
      series actually spans the window — first point at/before `start`,
      last point at/after `end − 1h`).
- [ ] Additional sanity checks: series is non-empty; timestamps land inside
      the requested window (catches the unit bug directly); no all-NaN; for
      temperatures a loose physical range (e.g. −60..80 °C) flagged as a
      warning, not a hard fail.
- [ ] Surface failures as a structured 400 (per node_id → reason), the same
      shape as the existing `errors` dict in `/simulate/run` and `/fit/run`,
      so the UI can show which signal is bad and why.
- [ ] Decide hard-fail vs warning per check (coverage = hard fail; physical
      range = warning) and thread warnings through to the run/fit result.

**Test:** unit tests on the validator — a >1 h gap fails; a window-spanning
15-min series passes; out-of-window timestamps (the unit-bug case) fail;
empty/all-NaN fails. API test: a study wired to a too-sparse signal returns
400 with a readable per-signal reason instead of a flat-line result.

---

## Step 6 — Bundled example house + dataset

The demo content, in the new study/view format.

- [ ] Generate (or download once via Open-Meteo archive) ~3 weeks of
      outdoor temperature + solar, plus a synthetic indoor temperature
      produced by the simulator from known params → commit as
      `data/datasets/example_winter.csv`.
- [ ] Commit `data/houses/example.json`: one room, two walls (one insulated,
      one not), one window, outdoor boundary; one fit study with its
      default view pre-built, pointing at the CSV signals.
- [ ] Because the indoor series is synthetic, the fit has a known right
      answer — the demo is also a self-check.

**Test:** `POST /fit/run` on the bundled study converges and recovers the
generating parameters (API-level test).

---

## Step 7 — Fit converges from untouched defaults

Most of old "workable fitting" is now structural (lumped element priors composed
from elements, Rse/Rsi folded, parallel grouping in the view). What's left:

- [ ] **Initial state burn-in**: `mode: "burnin"` (prepend N days, default 2,
      discard) on `/simulate/run` and `/fit/run`; default for fits.
- [ ] Verify composed priors are sane on the fixtures: zone `Ceq` from
      volume × 1200 J/m³K × furniture factor; chain priors from the layer
      stack (already in `wall_chains`).
- [ ] NLS first; MCMC stays available but is not on the demo path.

**Test:** the Step 6 fit converges with default fit config — asserted by
the Step 6 API test. Unit test for burn-in (result independent of T₀ guess).

---

## Step 8 — Results readable on the house (the payoff screen)

Minimal `attribute()`: posterior on lumped elements → element-level properties.
Well-defined now because each lumped element records which element it realizes.

- [ ] Back-map per lumped element: `RC_chain` posterior → element effective λ
      (single dominant layer) or U-value `1/(R·A)`, with σ; `Req` →
      U-value; `Ceq` → effective capacitance.
- [ ] Per-element badges in HousePanel after a fit: `U = 1.4 ± 0.3`,
      color-coded by posterior shift vs prior (confirms / contradicts the
      description).

**Test:** unit test for the back-mapping (incl. chain and shared-Req
fan-out); manual UI check that the example fit's badges match the known
generating params.

---

## Step 9 — Demo path & docs, release

- [ ] README quickstart rewritten around the no-Influx path: clone → sync →
      build → open example → Fit. Influx setup moves to a separate section.
- [ ] Update project_description.md: lumped/view sections replace the
      node-field fit description.
- [ ] Empty states in the UI: no houses → "open the example"; study with no
      signals → point at `data/datasets/`.
- [ ] `CHANGELOG.md` entry; tag `v1.0`.

**Test:** the acceptance scenario at the top of this file, executed by
someone (or a fresh agent session) following only the README, in under
10 minutes.

---

## Explicitly post-v1

Parked so v1 stays minimal — tracked in [roadmap.md](roadmap.md):

- Beliefs (confidence-typed quantities), domain layer, `attribute()` writing
  insights back as element priors, agent loop + trace
  ([modeling_pipeline.md](modeling_pipeline.md))
- View transforms: refine / coarsen / resolve / tie; multiple view depths
- SystemTemplate / compiled-rules hot path
  ([implementation.md](implementation.md)) — only if profiling demands it
- Merge Run into Fit; energy view; full results-by-element projection (M5)
- UI rework (DaisyUI, burger menu), floor-plan canvas, better RC graph viz
- Parquet/duckdb result persistence; rename house → model; slug filenames
- CSV upload UI; Open-Meteo live source; MCMC corner plot; cross-study
  learning
