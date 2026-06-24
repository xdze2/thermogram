# Documentation

Design and physics docs for the thermal RC modelling app. (App overview and run commands live in
the repo-root `CLAUDE.md`.)

## The modular RC model

The app is moving from a fixed 2R2C topology to a **modular** engine assembled from flux modules
that match a building's actual physics. The docs below are ordered from "why" → "what" → "how" →
"when".

| doc | role |
|---|---|
| [`modular_rc_proposal.md`](modular_rc_proposal.md) | **Why** — design rationale: the prior–fit divergence problem, the (element, channel) ownership idea, the two-uses-one-engine structure (simulate vs fit). |
| [`physics_model.md`](physics_model.md) | **What (source of truth)** — elements, channels `(mechanism, source)`, the four module forms, assembly, the RC↔thermal analogy. The physics doc wins on any conflict. |
| [`test_cases.md`](test_cases.md) | **Validation** — six buildings (cave, caravan, house, passive, Earthship, ITE/ITI wall) decomposed into channel→module tables. The Stage 0 expressiveness pass. |
| [`todo_modular_rc.md`](todo_modular_rc.md) | **When** — the test-first build roadmap (Stages 0–5 + deferred). |

## Diagrams

- [`diagrams/`](diagrams/) — generic per-module RC schematics (PNG + SVG).
- [`draw_modules.py`](draw_modules.py) — standalone generator for them. schemdraw is **not** a
  project dependency; run it transiently:
  ```bash
  uv run --with schemdraw --with matplotlib docs/draw_modules.py
  ```
  The engine-driven, per-study schematic renderer (`thermal/draw.py`) is Stage 4.

## Reference

- [`biblio/`](biblio/) — papers and reading notes. Notably
  [`biblio/reading_note_bacher_madsen_2011.md`](biblio/reading_note_bacher_madsen_2011.md) (the
  grey-box heat-dynamics method behind ③ the fit) and
  [`biblio/identifiability_bibliography.md`](biblio/identifiability_bibliography.md).
- [`screenshots/`](screenshots/) — UI captures.

## Reading order

New to the project? **proposal → physics_model → test_cases → todo.** Implementing a stage? Start
from `todo_modular_rc.md` and treat `physics_model.md` as the spec.
