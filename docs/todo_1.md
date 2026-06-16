# todo_1 — solver review findings

Review of `thermogram/solver` (physics, assemble, simulate, fit, lumps, view,
identifiability). Baseline at time of review: all 156 solver tests pass
(`uv run --with pytest pytest thermogram/solver/tests -q`).

Items are ordered by severity. Each is self-contained enough to pick up cold.

---

## 🔴 1. chain_n=1 opaque walls drop the entire bulk wall resistance

**Where:** `thermogram/solver/physics.py`, `_expand_opaque`, the chain loop at
[physics.py:316-347](../thermogram/solver/physics.py#L316-L347).

**Problem:** The loop only inserts an interior resistor *between consecutive
mass nodes* (`if i < N-1: ... add R_wall/N ...`). When `N == 1` there are zero
interior resistors, so `R_wall` (the bulk material resistance,
`R_total - R_se - R_si`) is **never added to the topology at all**. The wall
then conducts only through `Rse + Rsi`.

**Evidence (data/houses/new_house.json, wall "N", chain_n=1):**
- true `R_total = 0.5828`
- assembled path = `Rse + Rsi = 0.0566` (~10× too conductive)
- `R_wall = 0.5262` is silently dropped.

Any opaque wall whose material is thin/light enough that
`_opaque_chain_n` (`physics.py:145`) rounds to 1 is mismodeled this way.

**Fix direction:** The single mass node must still carry `R_wall`. Cleanest
options:
- Split `R_wall` as `R_wall/2` on each side of the mass node (mass sits in the
  middle of the wall), inserting two interior resistors flanking the lone mass,
  **or**
- Place one interior resistor of `R_wall` on one side of the mass.
  (Half-on-each-side is more physically symmetric and matches the lumped-mass
  convention; pick and document.)

The chosen layout must produce a non-empty interior R-node set so that #2 and
`apply_chain` work. After fixing, re-check `wall_chains[label]["r_ids"]` is
non-empty for N=1.

**Test to add:** assemble a single chain_n=1 opaque wall between an outdoor
boundary and a room; assert the steady-state conductance equals `1/R_total`
(within surface-resistance bookkeeping), not `1/(Rse+Rsi)`.

---

## 🔴 2. `get_chain_priors` returns R=0 for N=1 → `log(0) = -inf` into the optimizer

**Where:**
- `thermogram/solver/view.py`, `get_chain_priors`
  [view.py:469-484](../thermogram/solver/view.py#L469-L484) — sums interior-R
  nominals; for N=1 that set is empty ⇒ `R_nom = 0`.
- `thermogram/solver/fit.py`, `build_forward_from_view`
  [fit.py:517-521](../thermogram/solver/fit.py#L517-L521) — does
  `np.log(R_nom)` ⇒ `-inf` as the **initial guess** handed to `least_squares`.

**Evidence:** building the forward model on `new_house.json` emits a
`divide by zero encountered in log` RuntimeWarning and yields
`chain_..._R log_phi0 = -inf`.

**Compounding issue:** even if the `-inf` is patched, `apply_chain` with
`n_r == 0` ([lumps.py:100-103](../thermogram/solver/lumps.py#L100-L103))
distributes `phi_R` to *nothing*, so the wall's R is structurally unfittable.

**Fix direction:** This is downstream of #1 — once a chain_n=1 wall has a real
interior R node, `get_chain_priors` returns a positive `R_nom` and the problem
disappears. Fix #1 first, then re-verify this path. As a defensive guard,
consider asserting `R_nom > 0` in `get_chain_priors` (or
`build_forward_from_view`) so a future regression fails loudly instead of
silently feeding `-inf`.

**Test to add:** `build_forward_from_view` on a model containing a chain_n=1
wall must return a finite `log_phi0` for every entry, and a subsequent
`fit_nls_view` must recover a perturbed R.

---

## 🔴 3. R prior shown ≠ R prior fitted for N≥2 chains

**Where:**
- The lump stores `prior.nominal = R_wall` via `compose_chain_prior`
  ([view.py:247-249](../thermogram/solver/view.py#L247-L249),
  `compose_chain_prior` at
  [lumps.py:230-239](../thermogram/solver/lumps.py#L230-L239)).
- The fit re-derives its nominal from `get_chain_priors` = sum of the *interior*
  R nodes = `R_wall · (N-1)/N`
  ([fit.py:517](../thermogram/solver/fit.py#L517)).

**Evidence (new_house.json, wall "Inner", chain_n=4):**
`lump.prior.nominal (R_wall) = 0.08333` vs `get_chain_priors R_interior =
0.06250`, ratio `0.75 = (N-1)/N`.

So the prior the user sees on the View differs from the prior the fit actually
regularizes toward. Discrepancy grows as N shrinks.

**Fix direction:** Pick ONE definition of "the chain's R degree of freedom" and
use it consistently in `compose_chain_prior`, the lump's displayed prior, and
`get_chain_priors`/`build_forward_from_view`. Two coherent choices:
- (a) the DOF is the **interior** resistance `R_wall·(N-1)/N` — then
  `compose_chain_prior` should compose from interior nodes, not `R_wall`; or
- (b) the DOF is the **full** `R_wall` — then `get_chain_priors` /
  `apply_chain` should distribute `R_wall` over the interior nodes such that
  the total interior R equals the fitted φ_R (i.e. scale by `N/(N-1)`).

Once #1 changes the N=1 topology, re-confirm the chosen convention still holds
for N=1.

**Test to add:** for a chain with N≥2, assert
`get_chain_priors(...)[0] == lump.prior.nominal` (whichever convention wins).

---

## 🔴 4. `_is_outdoor_node` returns True for *any* boundary

**Where:** `thermogram/solver/physics.py`
[physics.py:228-231](../thermogram/solver/physics.py#L228-L231).

**Problem:** Named and documented as "outdoor/ground" but the body only checks
`node["kind"] == "boundary"`. A room with `role == "boundary"` is also a
boundary node, so `_expand_opaque` would treat it as the outdoor face — placing
`Rse` on the wrong side and injecting solar gain into the wrong surface
(`_expand_opaque` uses `outdoor_is_a/b` + `has_outdoor_face` at
[physics.py:296-300](../thermogram/solver/physics.py#L296-L300) and
[physics.py:358-375](../thermogram/solver/physics.py#L358-L375)).

Latent today — the sample houses don't combine a `role="boundary"` room with a
solar-bearing opaque wall — but the check doesn't match the name/intent.

**Fix direction:** distinguish true outdoor/ground from prescribed-temperature
rooms. Either tag outdoor/ground boundary nodes at creation (e.g. an
`is_environment: True` flag in `_ensure_zone_node` at
[physics.py:192-212](../thermogram/solver/physics.py#L192-L212)) and check that
flag, or look up the originating zone's `kind in ("outdoor","ground")` rather
than the node's RC kind.

**Test to add:** opaque wall between a `role="boundary"` room and a `mass` room,
with `solar_absorptance` + `solar_signal` set: assert no solar source node is
created (no outdoor face), and Rse/Rsi placement is unaffected by the boundary
room.

---

## 🟡 5. Retire the dead legacy fit path (decision needed)

The API uses **only** `build_forward_from_view` + `fit_nls_view`
([api/main.py:25](../thermogram/api/main.py#L25),
[api/main.py:612-626](../thermogram/api/main.py#L612-L626)). The following are
dead outside tests:

- In `thermogram/solver/fit.py` (~250 lines): `build_forward`, `fit_nls`,
  `fit_mcmc`, `expand_groups`, `_patch_model`, `_parse_key`.
- The whole `thermogram/solver/identifiability.py` module (`group_params`). Its
  parallel-R grouping is now done structurally by `build_default_view`
  (section 2 parallel-R merge), as view.py's own docstring states
  ([view.py:18](../thermogram/solver/view.py#L18)).
- `_patch_model`'s `wall_chains` fan-out is superseded by
  `lumps.apply_atom_values`.

Kept alive only by these tests:
- `thermogram/solver/tests/test_fit.py` (uses `_patch_model`, `build_forward`,
  `fit_nls`)
- `thermogram/solver/tests/test_roundtrip.py` (the **legacy half** —
  `build_forward` + `fit_nls`; the φ-path half stays)
- `thermogram/solver/tests/test_identifiability.py` (entire module)

**Decision required before acting:** docs/todo.md states the φ-space path is the
committed direction, which would make retiring this ~400 lines (solver + tests)
correct. But it means deleting tests, so confirm intent first.

**If retiring:** delete the functions above, delete `identifiability.py`, delete
`test_identifiability.py` and `test_fit.py`, and trim the legacy half of
`test_roundtrip.py` (keep `TestRoundtripView` / the φ-path test). Drop the
`from .identifiability import group_params` import in `fit.py` and the
`param_groups` field on `FitResult` if `FitResult` itself goes. Re-run the
suite; the φ-path roundtrip must still pass.

---

## 🟡 6. `fit_nls_view` docstring claims it wraps `fit_nls` — it doesn't

**Where:** `thermogram/solver/fit.py`
[fit.py:644-656](../thermogram/solver/fit.py#L644-L656).

The docstring says "Wraps fit_nls and maps the result back to ViewFitResult."
In fact it reimplements `least_squares` + the covariance/std computation inline.
The covariance block [fit.py:711-724](../thermogram/solver/fit.py#L711-L724) is
a near-duplicate of [fit.py:291-299](../thermogram/solver/fit.py#L291-L299) in
`fit_nls` — drift risk.

**Fix direction:** If #5 retires `fit_nls`, factor the shared least_squares +
covariance logic into a small private helper that both `fit_nls_view` and any
remaining caller use, and correct/remove the misleading docstring line. If
`fit_nls` stays, at minimum fix the docstring.

---

## 🟡 7. `_zone_node_kind` is dead and duplicates live logic

**Where:** `thermogram/solver/physics.py`
[physics.py:164-174](../thermogram/solver/physics.py#L164-L174).

Zero callers (`grep -rn _zone_node_kind` → only its own def). The same
role→kind decision is inlined in `_ensure_zone_node`
([physics.py:188-219](../thermogram/solver/physics.py#L188-L219)). Delete the
function.

---

## 🟢 8. Dead code / unused imports (low risk, mechanical)

- `physics.py`: `_RSI_INTERIOR`, `_RSI_EXTERIOR`
  ([physics.py:44-45](../thermogram/solver/physics.py#L44-L45)) and `_CP_AIR_KJ`
  ([physics.py:50](../thermogram/solver/physics.py#L50)) — defined, never read.
- `assemble.py`: `import json` and `from pathlib import Path`
  ([assemble.py:15-17](../thermogram/solver/assemble.py#L15-L17)) — unused.
- `lumps.py` unused imports: `field`, `Literal`, `numpy as np`, and from
  `thermogram.models` the names `CombineRule`, `FitMode`, `Posterior`, `View`
  (only `LumpedElement` and `Prior` are actually used)
  ([lumps.py:31-46](../thermogram/solver/lumps.py#L31-L46)).
- `view.py`: `_single_prior` re-imports `Prior` locally
  ([view.py:89-91](../thermogram/solver/view.py#L89-L91)) though `Prior` is
  already imported at module top ([view.py:36](../thermogram/solver/view.py#L36)).
  Drop the local import.
- `lumps.py`: `compose_series_prior`
  ([lumps.py:214-216](../thermogram/solver/lumps.py#L214-L216)) — no callers;
  `build_default_view` uses `_single_prior` for the single-R `series_sum` case
  instead. Remove unless a caller is planned.

---

## Verified non-issues (do NOT "fix")

- `model_hash` docstring says "elements list" but the caller correctly passes
  `elements + rooms` ([api/main.py:80](../thermogram/api/main.py#L80)). Behavior
  is correct; only the docstring is narrow.
- The resistance-chain walk in `assemble.py`
  ([assemble.py:55-85](../thermogram/solver/assemble.py#L55-L85)) has correct
  double-visit guards (`visited_starts` records both ends), no double-counting.
- `simulate_ivp` is still legitimately used by the API run endpoint
  ([api/main.py:370](../thermogram/api/main.py#L370)) — not dead.

---

## Suggested order of work

1. Fix **#1** (topology for N=1 walls) — physical correctness, hits real houses.
2. Verify **#2** is resolved by #1; add the defensive `R_nom > 0` guard.
3. Resolve **#3** (one consistent chain-R convention) alongside #1, since both
   touch how chain R is composed/distributed.
4. Fix **#4** (outdoor-node identification) independently.
5. Do **#8** (mechanical dead-code/imports) anytime.
6. Get a decision on **#5**; if go, also do **#6** and **#7** in the same pass.

Re-run `uv run --with pytest pytest thermogram/solver/tests -q` after each step.
