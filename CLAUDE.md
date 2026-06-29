# CLAUDE.md

Guidance for Claude Code working in this repository.

`thnodes` is a single-room dynamic thermal building simulation + parameter-identification
tool (FastAPI backend + Svelte frontend, pure-Python numerics). The engine (Steps 0–1) and
the Step-4a authoring app exist under `src/`, `frontend/`, `tests/`; the fit layer
(Steps 2–3) is not yet built.

## Start here

**Read `docs/specs/00_overview.md` first.** `docs/specs/` is the authoritative target-state
specification and gives the full reading order. When code and a spec disagree, the spec wins
(or it's wrong and must be fixed first). `docs/background/` holds the design rationale (the
*why*); `docs/roadmap.md` and `docs/TODO.md` hold sequencing.

## Hard constraints (do not violate without explicit sign-off)

- **Local, single-user, no auth, no multi-tenancy.** *(Amended 2026-06: the original
  "single-session, no save/load" rule is relaxed. The app now persists locally — each room
  is a UID-addressed document auto-saved to `user_data/{uid}.json`, with a multi-model home
  page (list / open / rename / remove / new-from-example). Still strictly local single-user:
  no auth, no DB, no remote storage, no multi-tenancy.)*
- **Physics runs server-side**, including topology rendering (schemdraw → SVG).
- **JAX stays contained to the fit layer (Steps 2–3).** The assembler, forward simulation,
  and identifiability lens (Steps 0–1) must not import JAX.
- The Kalman filter is **hand-rolled**, not a black-box state-space library
  (`statsmodels`/`filterpy`/`pykalman` are out).
- **CTSM-R is a validation oracle only** — never a runtime dependency. No R in the deploy.
- Python is `uv`-managed.
