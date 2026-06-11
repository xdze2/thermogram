- [x] own repo
- [x] move data dir out of code
- rename "house" to "model"
- data source page: import csv, open meteo api, influx, ...
- rework ui: burger menu, use daisyui.com
- help message, in app documentation (element text description)
- rename json with slug
- Workable fitting
  - Clean parameters choice -> lumped model layer!!
  - Mapping back to elements
- Energy view
- y0: fit, or estimate (bake)
- better RC graph viz
- Merge Fit and run, remove run, always do a fit (y0 only for instance)
- Proof read the code
- Persistent results stored: Parquet files, duckdb?

---

refs

The programme is IEA EBC Annex 58 ("Reliable Building Energy Performance Characterisation Based on Full Scale Dynamic Measurements"), and the follow-up Annex 71 ("Building Energy Performance Assessment Based on In-situ Measurements"). Both focus specifically on identifying thermal parameters (R, C) from in-situ temperature measurements
