# thermogram

Describe a house room-by-room, expand
into a thermal RC network, run forward simulations against weather data, and
fit model parameters to sensor data.

```
[house description]  →  physics layer  →  RC graph  →  assembler  →  ODE
 material, area, λ       expand walls       R, C, edges    A, B matrices
```

Single-house app. The UI is a **split view**: house pane on the left (the noun,
modes: `edit | simulate`), study pane on the right (the verb, modes: `run | fit`).
Studies are spawned from a house selection — pick rooms, pick a period, run.
Results project back onto house element tiles via an expansion map.

The miniha parent project handles **data capture and logging** (InfluxDB).
thermogram consumes that data for **model identification**.

## Screenshots

<p align="center">
  <img src="screenshots/graph_topo_070626.png"     width="420" alt="Topology editor" />
  <img src="screenshots/inputs_07062026.png"       width="420" alt="Inputs tab" />
  <img src="screenshots/run_results_07062026.png"  width="420" alt="Simulation run" />
  <img src="screenshots/fit_results_03072026.png"  width="420" alt="Fit results" />
</p>

## Stack

| Layer                | Choice                                       |
| -------------------- | -------------------------------------------- |
| Model + study format | JSON                                         |
| Solver               | Python — `scipy` (IVP/BDF + ZOH)             |
| Data source          | InfluxDB (via `GET /signals`, `GET /series`) |
| API                  | FastAPI (port 8001)                          |
| UI                   | SvelteKit + `@xyflow/svelte` + uPlot         |

## Running

```bash
# API
uv run uvicorn thermogram.api.main:app --reload --port 8001

# UI
cd thermogram/ui
npm install        # first time only
npm run dev        # http://localhost:5173
```

## Docs

- **[project_description.md](project_description.md)** — current state, architecture,
  data model, API surface, design decisions
- **[todo.md](todo.md)** — open work and changelog
