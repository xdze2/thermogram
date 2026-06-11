- own repo
- move data dir out of code
- rename "house" to "model"
- data source page: csv, open meteo, influx, ...
- rework ui: burger menu, theme
- help message, in app documentation (element text description)
- rename json with slug
- Workable fitting
  - Clean parameters choice
  - Mapping back to elements
- Energy view
- y0: fit, or estimate (bake)
- better RC graph viz
- Merge Fit and run, remove run, always do a fit (y0 only for instance)
- Model -> RC Graph. Time range+inputs -> Fit -> Results
- Proof read the code
- Optimisation, or find a solver (spice?)
  - time the entire endpoint call (vs only the solver call)
  - write the assemble part in C (Rust, ...)?

---

model physical description (material and geometry)
-> approximation to a RC graph

physics param with prior: (fixed, incertain, range, multimodal)
rc graph should be minimal
we want to estimate physical parameter, but not in full detail

- R for a room, no need to estimate each part
- (R, C) for a heavy wall

expand(model_phy) -> rc_graph, param_phi, mapping_fct(param_phi) -> theta, mapping_inverse(theta)-> param_phi

rc_solver(graph, y_0, theta, input_t) -> y_t

---

refs

The programme is IEA EBC Annex 58 ("Reliable Building Energy Performance Characterisation Based on Full Scale Dynamic Measurements"), and the follow-up Annex 71 ("Building Energy Performance Assessment Based on In-situ Measurements"). Both focus specifically on identifying thermal parameters (R, C) from in-situ temperature measurements
