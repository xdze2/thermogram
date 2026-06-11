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

## Step 2 — Lumped model layer in the solver (φ-space)

Minimal version of the lumped model layer from modeling_pipeline.md. Scope cuts
to keep it v1-sized:

- **Atoms = current `atomic_model` nodes.** No rewrite of `physics.py`; lumped
  elements overlay the existing `expand()` output, referencing atomic node ids.
- **No Belief objects.** Priors are `(nominal, sigma_log)` pairs composed at
  view-build time from element data (materials, geometry).
- **No transform ops** (refine/coarsen/tie) and no agent — only `free` /
  `fixed` modes on each lumped element.

Tasks:

- [ ] `solver/lumps.py` — `LumpedElement` dataclass (id, kind, atoms, combine,
      prior, mode, posterior) and the five combine rules: `series_sum`,
      `parallel_sum`, `parallel_inv_sum`, `chain`, `identity`. Pure
      functions `phi → atom values` with prior-derived weights (φ = prior
      ⇒ atoms = their nominals).
- [ ] `solver/view.py` — `build_default_view(atomic_model, expansion_map) → View`,
      deterministic, one depth for v1:
      - opaque element → one `RC_chain(n)` lumped element, 2 φ (R_total, C_total);
        **Rse / Rsi folded into the chain's series weights** — fixed share,
        not free φ (kills today's series-identifiability trap structurally);
      - glazing / air_exchange → `Req`; parallel R between the same node
        pair → one shared `Req` (replaces `identifiability.group_params`);
      - room → `Ceq`; boundaries / sources → `identity`, mode `fixed`.
- [ ] Rework `solver/fit.py`: `build_forward(view, ...)` takes the View;
      the residual closure maps log-φ → atom values → patched atomic model →
      assemble → simulate. Delete `_patch_model`'s label conventions and
      `fit_config["params"]`; retire `identifiability.group_params` (its
      logic moves into `build_default_view`).
- [ ] Posteriors land on the lumped elements (`value ± sigma_log`), not on
      atomic node fields.

**Test:** unit tests per combine rule (round-trip φ ↔ atoms, prior
consistency); `build_default_view` on the fixture houses asserts lumped element
count, coverage (every fittable atom covered exactly once), and Rse/Rsi
folding. The Step 1 round-trip re-run through the φ path recovers the same
ground truth — that test is then switched over permanently.

---

## Step 3 — Data model + API adaptation

The study persists the View; results are posteriors on lumped elements.

- [ ] Study schema: replace `fit.params` config with an embedded `view`:
      list of lumped elements (id, kind, atom ids, combine, prior, mode) +
      `fit.posteriors` keyed by lumped element id. Bump `schema_version`; write a
      one-shot migration for existing house files (or accept dropping old
      fit configs — decide, document).
- [ ] `model_hash` staleness extends to the view: if the house changed,
      the persisted view's atom refs may dangle → study flagged stale, view
      rebuilt on demand.
- [ ] API:
      - `POST /houses/{name}/studies/{id}/view` — (re)build the default
        view, persist it, return it;
      - `GET .../view` — current view with stale flag;
      - `PUT .../view` — update modes / prior overrides only (structure is
        always the default build for v1);
      - `/fit/run` takes the persisted view; rejects if stale.
- [ ] `/fit/preview-groups` removed (subsumed by the view).

**Test:** API-level tests — create study → build view → flip a lumped element to
`fixed` → fit → posteriors persisted under lumped element ids; edit house →
view flagged stale → rebuild regenerates consistent atom refs. Migration
test on a copy of a real house file.

---

## Step 4 — UI adaptation: FitPanel becomes the φ-table

- [ ] FitPanel rewritten as the φ-space table, one row per lumped element:
      label (from realizing element), kind badge, prior (nominal ± σ_log,
      human units), mode toggle (free/fixed), posterior ± σ after fit,
      prior→posterior shift indicator.
- [ ] Remove the node-field param table and its grouping preview UI.
- [ ] "Rebuild view" button when the study is stale (calls `POST .../view`).
- [ ] Simulation tab unchanged except: post-fit forward sim uses lumped element
      posteriors (φ → atoms) instead of `param_overrides` node patches.

**Test:** manual UI pass on a fixture house — build view, freeze a lumped element,
fit, see posteriors in the table; stale → rebuild flow works. Keep it to
one afternoon of polish; looks are post-v1.

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
