refs

The programme is IEA EBC Annex 58 ("Reliable Building Energy Performance Characterisation Based on Full Scale Dynamic Measurements"), and the follow-up Annex 71 ("Building Energy Performance Assessment Based on In-situ Measurements"). Both focus specifically on identifying thermal parameters (R, C) from in-situ temperature measurements

BOPTEST / BuildingsPy — Python libraries for building simulation, too complex for your purpose
estimators in scikit-learn — you could fit the RC model as a grey-box identification problem with scipy.optimize or a Kalman filter
pvlib — excellent Python library for solar irradiance calculation from position + weather, already used in HA integrations
Open-Meteo API — free, no key required, gives historical + forecast outdoor T, solar radiation, wind — perfect for correlating against indoor measurements

---

What exists in HA — 4 distinct approaches

1. Thermal comfort indices — thermal_comfort (HACS, well-maintained) computes dew point, heat index, humidex, perceived temperature from T + RH sensors. It provides bio indices like humidex and heat index giving human perceived "feels like" temperatures, plus textual perception sensors like "comfortable" or "uncomfortable". Useful as a sensor layer but no building model — purely instantaneous, no identification. GitHub
2. Home Performance — a December 2025 custom integration, directly relevant. It calculates a room's K coefficient (thermal loss), gives an insulation rating A to G, tracks energy consumption, and detects open windows in real-time. Built by someone who bought a 1930s house and wanted to know if their insulation was working. This is the closest to building identification in the HA ecosystem — but still focused on winter/heating mode, and it requires knowing the heating power input (heater wattage), which makes it hard to use in a pure passive diagnostic scenario with no active heating. Home Assistant
3. Heating Analytics — brand new (February 2026, still in testing). A local ML model that learns a house's thermal inertia, solar impact, and wind heat-loss over time to predict heating energy needs in kWh. One community member is combining it with a 3R2C thermal model fed by historical data — that's the RC circuit approach used in academic building identification. Very heating-focused, not yet a diagnostic tool, but the underlying model is essentially what you'd want. Home Assistant
4. RoomMind/RoomSense — MPC-based climate control. Uses a per-room thermal model with an Extended Kalman Filter that learns heating/cooling behaviour over time, plus solar gain awareness that estimates each room's solar response from sun position and weather data. Sophisticated but entirely control-oriented — the model identification is a means to better control, not an output you can read. GitHub
