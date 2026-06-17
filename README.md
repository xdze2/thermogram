# Thermal Room Estimator

A small engineering app for estimating the thermal parameters of a room, built on ISO standards and real weather data.

## What it does

The user describes a room **element by element** — walls, windows, roof, floor — specifying geometry, orientation, and material layers. The app computes steady-state thermal performance (ISO 6946 U-values) and runs an hourly dynamic simulation (ISO 52016 RC model) driven by real historical weather fetched automatically from Open-Meteo.

## Key outputs

**Static (per element and total)**
- U-value [W/m²·K] computed from material layer stack
- Total thermal resistance R [m²·K/W]
- Heat loss coefficient UA [W/K] per element and total
- Effective thermal mass κ [kJ/m²·K]
- Time constant τ [h] of the zone

**Dynamic (hourly, full year)**
- Annual heating and cooling energy [kWh/yr and kWh/m²·yr]
- Peak heating and cooling loads [W]
- Monthly energy demand and mean temperatures
- Hourly detail view for selected weeks
- Annual energy balance: solar gains, internal gains, conduction losses, ventilation losses

## Physics and standards

| Module | Reference |
|---|---|
| U-value from material layers | EN ISO 6946:2017 |
| Surface resistances (Rsi, Rso) | EN ISO 6946:2017 Table 1 |
| Material properties (λ, ρ, cp) | EN ISO 10456 / EN 1745 |
| Solar declination & hour angle | Spencer (1971) |
| Irradiance on tilted surface | Isotropic sky diffuse model (Hottel-Woertz) |
| Hourly RC thermal simulation | ISO 52016-1:2017 simplified 1-node method |
| Ventilation heat loss H_ve | ρ·cp·n·V (standard air properties) |
| Weather data | Open-Meteo historical archive (ERA5-based) |

The dynamic model represents the room as a single thermal node with a lumped capacitance C = κ · A_floor. At each hourly timestep an explicit Euler integration computes the free-float temperature, then ideal HVAC clamps it to the heating/cooling setpoint band. The HVAC demand at each step is the energy balance residual.

## Project structure

```
thermal/
  materials_db.py   # 30+ materials with λ, ρ, cp
  models.py         # Room, EnvelopeElement, MaterialLayer dataclasses
  iso6946.py        # U-value, R, UA, thermal mass calculations
  solar.py          # Solar geometry and surface irradiance
  weather.py        # Open-Meteo fetch and statistics
  rc_simulation.py  # Hourly RC simulation and annual summary
app.py              # Streamlit UI
```

## Running

Requires [uv](https://github.com/astral-sh/uv).

```bash
uv run streamlit run app.py
```

Weather data is fetched automatically (no API key needed) and cached in the session for the selected location and year.

## Scope and limitations

- Single-zone model: one thermal node per room, no inter-room heat transfer
- Opaque elements use the ISO 6946 series resistance method (no thermal bridging correction)
- Ground-contact floor uses a simplified boundary condition (no ISO 13370 ground coupling)
- Solar model uses isotropic diffuse sky; no shading or horizon masking
- HVAC is ideal (infinite capacity, 100% efficiency) — outputs are net energy demand, not primary energy
