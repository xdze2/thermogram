# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

This is a **greenfield repository**: it currently contains only design documents under `docs/`.
There is no source code, build tooling, tests, or dependency manifest yet. The first
implementation work will create the project scaffold described below.

- `docs/app_proposal.md` — the full design of the engine. **Read this before writing any code.**
- `docs/biblio/reading_note_bacher_madsen_2011.md` — the method reference for the fit layer
  (phase 2). Distinguishes what transfers from the Bacher & Madsen (2011) grey-box approach and
  what does not, given this project's passive/collinear data regime.
- `docs/biblio/*.pdf` is gitignored (`docs/biblio/.gitignore`).

## What this app is

`thnodes` is a single-room dynamic thermal building simulation + parameter-identification tool.
A user describes a room physically (walls, windows, floor, HVAC…); the app builds a minimal RC
(resistor–capacitor) equivalent model and either:

1. **Simulates** indoor temperature `T_room` forward from weather/scenario inputs, or
2. **Fits** the thermal parameters from sensor data via Bayesian inference (MAP).

## Intended tech stack (from the proposal — not yet present)

- **Backend:** FastAPI (Python, managed with `uv`). Local, single-user, single-session. Physics
  runs **server-side**, including topology rendering (schemdraw → matplotlib → static SVG/PNG).
- **Frontend:** Svelte + DaisyUI.
- **Numerics:** pure Python (NumPy + `scipy.optimize`). A hand-rolled 2-state LTI Kalman filter
  is preferred over `statsmodels`/`filterpy` for the fit. **CTSM-R is a validation oracle only,
  never a runtime dependency** — do not introduce an R runtime into the deploy.
