# Implementation

How the pipeline described in [modeling_pipeline.md](modeling_pipeline.md) is
realized in code. Companion to that doc — the modeling pipeline says *what
the objects are*; this one says *how the code is organized to make fitting
fast without sacrificing the clarity of the View-level model*.

The central design move is to **split assembly into two functions**, one
cold and one hot. Everything else follows from that split.

---

## The hot path vs. the cold path

A fit loop looks like this:

```
per study:
  build_atoms, build_domain        ← once
  propose_view / transform_view    ← once per agent decision
  assemble (View → SystemTemplate) ← once per view change   ★ cold
  fit:
    for each iteration:
      patch (φ → A, B values)      ← per iteration           ★ hot
      simulate                      ← per iteration           ★ hot
      residuals                     ← per iteration
```

The Python-y graph walking — visiting pseudos, expanding them into atoms,
resolving combine rules, assigning matrix indices — happens **once per
view change**. An NLS fit runs it once. A 100k-sample MCMC run still runs
it once. The hot path inside the fit loop never sees pseudos, never walks
graphs, never traverses dataclasses — it sees a flat numerical structure
and updates a small number of array entries.

This means the *interesting* code (assemble) can be as readable and
Pythonic as we want. The *fast* code (patch + simulate) is small, regular,
and easy to optimize incrementally.

```
┌──────────────────────────────────────────────────────────────┐
│ COLD: View → SystemTemplate                                   │
│                                                                │
│   Walk pseudos. Expand atoms via combine rules. Assign        │
│   state and input indices. Record sparsity pattern. Build     │
│   per-pseudo "compiled" combine rules (small array ops).      │
│   Output: SystemTemplate (numerical, no Python objects in     │
│           the hot path).                                       │
│                                                                │
│   Runs: once per view change. Python-friendly, dataclasses,   │
│         dicts, nested loops — all fine.                        │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│ HOT: (SystemTemplate, φ) → (A, B)                             │
│                                                                │
│   Evaluate compiled combine rules → atom values (one array).  │
│   Scatter atom values into preallocated A and B at            │
│   precomputed (i, j) indices.                                  │
│   Output: filled A, B matrices ready for simulate.            │
│                                                                │
│   Runs: every fit iteration. Pure NumPy array ops. No Python  │
│         loops over pseudos or atoms.                           │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│ HOT: (A, B, inputs, y0) → trajectory                          │
│                                                                │
│   ZOH stepper with precomputed exp(A·dt). Vectorized over     │
│   timesteps (BLAS does the work).                              │
└──────────────────────────────────────────────────────────────┘
```

---

## SystemTemplate — what it is and why

`SystemTemplate` is the **frozen, numerical** version of a View. It carries
everything `patch` needs to produce `(A, B)` from a φ-vector, in a form
NumPy can chew through without touching any Python objects.

Think of it as the *compiled* output of `assemble`. The View is symbolic
(pseudos, combine rules, provenance); the SystemTemplate is numerical
(arrays of indices, arrays of structural values, a small program for
each combine rule).

```python
@dataclass(frozen=True)
class SystemTemplate:
    # --- Shape ---
    n_states: int                       # number of mass nodes (C atoms)
    n_inputs: int                       # number of driven boundaries (T, Q)
    n_phi:    int                       # number of free pseudo parameters

    # --- φ → atom values ---
    # For each combine rule kind that appears in this template,
    # a compiled op describes how φ entries become atom values.
    # See "Compiled combine rules" below.
    compiled_rules: CompiledRules

    # --- Atom → matrix slot ---
    # Every atom value, once computed, lands at a specific (i, j)
    # in A or B with a specific sign and conductance role.
    # These tables are precomputed at assemble time.
    R_targets: RTargetTable      # how each R atom contributes to A
    C_targets: CTargetTable      # how each C atom scales A row (1/C)
    T_targets: TTargetTable      # how each T atom contributes to B
    Q_targets: QTargetTable      # how each Q atom contributes to B

    # --- Structural part (φ-independent) ---
    # If any A/B entries are constant (e.g. C from a "known" mass),
    # they're baked into these once.
    A_structural: np.ndarray | sparse.csr_matrix
    B_structural: np.ndarray | sparse.csr_matrix

    # --- Provenance (cold only — for diagnostics, not used in patch) ---
    phi_names:   tuple[str, ...]        # canonical order
    phi_priors:  tuple[Prior, ...]
    atom_ids:    tuple[str, ...]        # for back-tracing
    state_names: tuple[str, ...]        # for plotting

    # --- Hot-path workspace (preallocated) ---
    # Patch fills these in-place to avoid per-iteration allocation.
    A_buffer: np.ndarray                # shape (n_states, n_states)
    B_buffer: np.ndarray                # shape (n_states, n_inputs)
    atom_values: np.ndarray             # shape (n_atoms,)
```

The key properties:

- **No Python objects referenced in the hot path.** Every field used by
  `patch` is a NumPy array or a small struct of NumPy arrays. `phi_names`,
  `atom_ids`, `phi_priors` are kept for diagnostics but `patch` never
  reads them.
- **Indices are precomputed.** `R_targets.row`, `R_targets.col`,
  `R_targets.sign` are integer/float arrays. `patch` does
  `A[R_targets.row, R_targets.col] += sign * conductance`, full stop.
- **Workspace is preallocated.** `A_buffer`, `B_buffer`, `atom_values` are
  allocated once at assemble time and reused every iteration. No allocation
  inside the fit loop.

### Why frozen

`SystemTemplate` is immutable after `assemble` returns. `patch` does not
mutate the template — it writes into the preallocated buffers stored *on*
the template, and returns views into them. (Or, equivalently, returns a
freshly allocated `AssembledSystem` per call — design choice, see "Buffer
ownership" below.)

This matters for two reasons:
- Sharing one template across parallel MCMC chains is safe (each chain
  has its own buffers; the template's index tables are read-only).
- Caching: if the View hasn't changed, the template doesn't need rebuilding
  between successive `fit` calls.

---

## Compiled combine rules

The pseudo layer has a closed set of combine rules:

```
series_sum         Req from N series R atoms:       R_atom_i = φ × w_i,    Σ w_i = 1
parallel_inv_sum   Req from N parallel R atoms:     1/R_atom_i = (1/φ) × w_i
parallel_sum       Ceq from N parallel C atoms:     C_atom_i = φ × w_i
chain              RC_chain(n) with 2 φ's:          R_atom_i = φ_R / (n+1),  C_atom_i = φ_C / n
identity           T or Q exposed directly:         atom_value = φ
```

(The weights `w_i` are precomputed at assemble time from atom-level
prior values: e.g. for series-sum, w_i = R_prior_i / Σ R_prior_j, so that
when φ equals the prior, the atom values match the prior.)

Each rule reduces to a small NumPy expression that maps a slice of φ to a
slice of `atom_values`. At assemble time we group all atoms by their rule
kind and produce one batched operation per kind:

```python
@dataclass(frozen=True)
class CompiledRules:
    # For each rule kind, a struct with:
    #   - phi_indices:  which φ entries feed this rule (int array)
    #   - atom_indices: which atom_values entries this rule writes (int array)
    #   - weights:      precomputed per-atom weights (float array)
    #   - n_per_group:  for chains, the chain length n (int array)
    series_sum:        BatchedRule
    parallel_inv_sum:  BatchedRule
    parallel_sum:      BatchedRule
    chain:             BatchedChainRule
    identity:          BatchedRule

@dataclass(frozen=True)
class BatchedRule:
    phi_indices:  np.ndarray   # shape (n_atoms_in_group,)
    atom_indices: np.ndarray   # shape (n_atoms_in_group,)
    weights:      np.ndarray   # shape (n_atoms_in_group,)
```

The hot-path evaluator is then five NumPy lines, one per rule:

```python
def evaluate_combine_rules(rules: CompiledRules, phi: np.ndarray,
                           atom_values: np.ndarray) -> None:
    # series_sum:    atom = φ × weight
    r = rules.series_sum
    atom_values[r.atom_indices] = phi[r.phi_indices] * r.weights

    # parallel_inv_sum:    atom = φ / weight   (weight here is inverse share)
    r = rules.parallel_inv_sum
    atom_values[r.atom_indices] = phi[r.phi_indices] * r.weights

    # parallel_sum:  same shape as series_sum
    r = rules.parallel_sum
    atom_values[r.atom_indices] = phi[r.phi_indices] * r.weights

    # chain:         two φ entries per chain, n atoms per φ
    c = rules.chain
    atom_values[c.R_atom_indices] = phi[c.R_phi_indices] / c.R_divisor
    atom_values[c.C_atom_indices] = phi[c.C_phi_indices] / c.C_divisor

    # identity:      atom = φ
    r = rules.identity
    atom_values[r.atom_indices] = phi[r.phi_indices]
```

No Python loops over individual pseudos. The number of distinct rule kinds
is fixed (currently five); adding a new pseudo kind means adding one
batched array op.

---

## Target tables — atom → matrix scatter

Once atom values are computed, they scatter into A and B at precomputed
positions. Each atom contributes to specific matrix cells with specific
signs.

### R atoms (conductances in A)

A resistor R between nodes i and j contributes:

```
A[i,i] -= 1/R / C_i
A[i,j] += 1/R / C_i
A[j,j] -= 1/R / C_j
A[j,i] += 1/R / C_j
```

(If either i or j is a boundary, the corresponding rows are absent and
the contribution goes into B instead.)

We precompute, per R atom, the (row, col, sign, C_index) tuples — up to
four of them, or fewer if one side is a boundary:

```python
@dataclass(frozen=True)
class RTargetTable:
    atom_idx:  np.ndarray   # which atom_values entry this row reads from
    row:       np.ndarray   # A row
    col:       np.ndarray   # A col (or boundary index for B)
    sign:      np.ndarray   # ±1
    c_idx:     np.ndarray   # which atom_values entry is the C this row's normalized by
    target:    np.ndarray   # 0 = A, 1 = B
```

The patch step for R is then:

```python
G = 1.0 / atom_values[R_targets.atom_idx]            # conductances
C = atom_values[R_targets.c_idx]                     # mass normalization
contrib = G * R_targets.sign / C
# Scatter into A and B
mask_A = R_targets.target == 0
A_buffer[R_targets.row[mask_A], R_targets.col[mask_A]] = contrib[mask_A]
B_buffer[R_targets.row[~mask_A], R_targets.col[~mask_A]] = contrib[~mask_A]
```

(For sparsity-preserving updates use `np.add.at` or scipy.sparse COO
construction; the choice depends on whether `n_states` justifies sparse.)

### C atoms (mass normalization)

C atoms don't add to A directly — they normalize the A and B rows they
correspond to. Conceptually `A` is `M^{-1} K` where M is diagonal of C's
and K is the conductance matrix. We've folded the `M^{-1}` into the
per-row scaling above (via `c_idx`).

### T_boundary atoms (driven node temperatures)

These appear in B and in the input vector u(t). Their atom value is the
temperature signal index, not a number — but the *gain* from boundary into
each row depends on the connecting R, already handled above. So
`TTargetTable` only records which input channel each boundary maps to.

### Q_source atoms (injected power)

These add to B rows directly, scaled by 1/C of the receiving node.

```python
@dataclass(frozen=True)
class QTargetTable:
    row:       np.ndarray   # which state row
    input_idx: np.ndarray   # which input channel
    c_idx:     np.ndarray   # normalize by this C
```

---

## The patch function in full

```python
def patch(tmpl: SystemTemplate, phi: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    # 1. φ → atom values (5 NumPy lines, one per rule kind)
    evaluate_combine_rules(tmpl.compiled_rules, phi, tmpl.atom_values)

    # 2. Reset buffers to structural defaults
    np.copyto(tmpl.A_buffer, tmpl.A_structural)
    np.copyto(tmpl.B_buffer, tmpl.B_structural)

    # 3. Scatter R contributions
    G        = 1.0 / tmpl.atom_values[tmpl.R_targets.atom_idx]
    C_norm   = tmpl.atom_values[tmpl.R_targets.c_idx]
    contrib  = G * tmpl.R_targets.sign / C_norm
    mask_A   = tmpl.R_targets.target == 0
    np.add.at(tmpl.A_buffer,
              (tmpl.R_targets.row[mask_A],  tmpl.R_targets.col[mask_A]),
              contrib[mask_A])
    np.add.at(tmpl.B_buffer,
              (tmpl.R_targets.row[~mask_A], tmpl.R_targets.col[~mask_A]),
              contrib[~mask_A])

    # 4. Scatter Q contributions
    q_contrib = 1.0 / tmpl.atom_values[tmpl.Q_targets.c_idx]
    np.add.at(tmpl.B_buffer,
              (tmpl.Q_targets.row, tmpl.Q_targets.input_idx),
              q_contrib)

    return tmpl.A_buffer, tmpl.B_buffer
```

That's the entire hot-path matrix construction. No Python-level iteration
over pseudos or atoms. The only loops are inside NumPy.

---

## Assemble — the cold path

`assemble` does the work of walking the View, expanding pseudos, allocating
atom and state indices, and producing the target tables. It's allowed to be
slow (relatively) and clear.

```python
def assemble(view: View) -> SystemTemplate:
    # 1. Expand each pseudo into its atoms.
    #    Atom list is canonical: every atom has a stable id and an index.
    atoms = []
    for pseudo in view.pseudos:
        atoms.extend(expand_pseudo(pseudo))   # returns list[Atom]
    atom_index = {a.id: i for i, a in enumerate(atoms)}

    # 2. Assign state indices to C-atoms (each C becomes a state row).
    state_atoms = [a for a in atoms if a.kind == "C"]
    state_index = {a.id: i for i, a in enumerate(state_atoms)}

    # 3. Assign input indices to driven boundaries.
    input_atoms = [a for a in atoms if a.kind in ("T_boundary", "Q_source")]
    input_index = {a.id: i for i, a in enumerate(input_atoms)}

    # 4. Build target tables by walking R atoms and looking up their endpoints.
    R_targets = build_R_targets(atoms, atom_index, state_index, input_index)
    C_targets = build_C_targets(atoms, atom_index, state_index)
    Q_targets = build_Q_targets(atoms, atom_index, state_index, input_index)
    T_targets = build_T_targets(atoms, atom_index, input_index)

    # 5. Compile combine rules by grouping pseudos by kind.
    compiled = compile_rules(view.pseudos, atom_index)

    # 6. Allocate buffers.
    n = len(state_atoms)
    m = len(input_atoms)
    A_buf = np.zeros((n, n))
    B_buf = np.zeros((n, m))
    atom_vals = np.zeros(len(atoms))

    # 7. Bake structural (φ-independent) part — for "fixed" pseudos.
    A_struct, B_struct = bake_structural(view, atoms, ...)

    return SystemTemplate(
        n_states=n, n_inputs=m, n_phi=count_free(view),
        compiled_rules=compiled,
        R_targets=R_targets, C_targets=C_targets,
        Q_targets=Q_targets, T_targets=T_targets,
        A_structural=A_struct, B_structural=B_struct,
        phi_names=tuple(p.id for p in view.pseudos if p.mode == "free"),
        phi_priors=tuple(p.prior for p in view.pseudos if p.mode == "free"),
        atom_ids=tuple(a.id for a in atoms),
        state_names=tuple(a.source for a in state_atoms),
        A_buffer=A_buf, B_buffer=B_buf, atom_values=atom_vals,
    )
```

This is Python at its most pedestrian — list comprehensions, dict lookups,
small helpers. It's clear, debuggable, easy to evolve. None of it runs in
the fit loop.

---

## Module layout

```
solver/
  beliefs.py          # Belief, prior composition
  elements.py         # Element schema, house loader
  atoms.py            # Atom, build_atoms
  domain.py           # build_domain
  pseudos.py          # Pseudo, expand_pseudo, combine rule logic
  view.py             # View, propose_view, transform_view

  assemble.py         # ★ COLD — View → SystemTemplate
  template.py         # ★ SystemTemplate, CompiledRules, target tables
  patch.py            # ★ HOT — (SystemTemplate, φ) → (A, B)
  simulate.py         # ★ HOT — ZOH stepper, simulate_zoh, simulate_ivp

  fit.py              # build_forward(view, study) → residuals(φ); wraps scipy
  attribute.py        # FitResult → BeliefUpdates

agent/
  tools.py            # tool wrappers exposed to the LLM
  loop.py             # agent loop, trace recording
```

The cold/hot split is enforced by the module split: `assemble.py` imports
freely from the View-layer modules; `patch.py` imports only `template.py`
and NumPy. Anything reaching from `patch.py` into a Python-level object
graph is a bug.

---

## Buffer ownership and concurrency

Two design choices on how `patch` returns its result:

**Option A: In-place, return views.** Patch mutates `tmpl.A_buffer` and
`tmpl.B_buffer`, returns them as-is. Zero allocation per call. Downside:
the SystemTemplate is no longer safe to share across threads (MCMC chains).

**Option B: Per-call allocation.** Patch allocates fresh A, B each call.
Simpler ownership; one allocation per fit iteration is cheap at this size.
Threads can share the template freely.

**Option C: Template-per-chain.** For parallel MCMC, build N templates
(cheap — assemble runs once and we copy buffers), each owned by one
chain. Combines the speed of A with the safety of B.

Default to **B** until profiling says otherwise. The allocation cost of two
small dense matrices is negligible compared to `expm` and matrix-multiply
in `simulate`.

---

## Where each language consideration lives

Recall the four candidates: pure Python+scipy, Python+C/Numba, Julia, JAX.

| Concern                          | Cold (`assemble`) | Hot (`patch` + `simulate`) |
|---|---|---|
| Code clarity / evolvability      | matters a lot     | matters less                |
| Performance                      | doesn't matter    | matters a lot               |
| Debuggability                    | Python wins       | doesn't matter much         |
| Cross-language friction          | high cost         | one well-defined kernel     |

Conclusion: cold path stays in pure Python, forever. Hot path stays in
NumPy initially, and is small enough that **if profiling later demands it,
we can rewrite just `patch.py` + the simulate stepper** in Numba, JAX, or
C without touching anything else. The SystemTemplate is the stable
interface that protects this option.

---

## Performance budget

For the target use case (rooms with ~10–30 states, ~100–500 timesteps per
solve, MCMC with ~10⁵ samples):

| Step                          | Per-call cost (estimated) | Frequency      |
|---|---|---|
| `assemble`                    | 1–10 ms                   | once per view  |
| `evaluate_combine_rules`      | ~5 µs                     | per iteration  |
| matrix scatter (`np.add.at`)  | ~20 µs                    | per iteration  |
| `expm` (10×10)                | ~50 µs                    | per iteration  |
| ZOH stepping (300 steps)      | ~200 µs                   | per iteration  |
| Total per iteration           | ~300 µs                   | —              |
| MCMC 10⁵ samples              | ~30 s                     | per run        |

These are within scipy/NumPy reach without acceleration. If
`evaluate_combine_rules` + scatter ends up dominating (it shouldn't),
Numba-jit on those two functions is a 5-line change.

---

## What this implementation doesn't do (yet)

- **Sensitivities / Jacobians of the trajectory w.r.t. φ** — needed for
  HMC/NUTS. Not in scope for the v1 NLS+random-walk-MCMC fit. When needed,
  the path is to JAX-ify `patch` and `simulate_zoh` together so AD passes
  through the whole forward pass. The SystemTemplate is already shaped for
  this (no Python objects in the hot path).
- **Time-varying A** — modulators that change R or C in time
  (e.g. shutter open/closed) would require `patch` to be called inside
  the stepper, or for the stepper to support piecewise-constant A.
  Deferred until we have a concrete use case.
- **Nonlinear modulators** (radiation `T⁴`, control laws with feedback)
  — out of scope for the linear-system template. Would require a different
  template kind with a residual-evaluator closure.

---

## TL;DR

- One function (`assemble`) is large, Pythonic, runs once per View. Lives in clear code.
- One function (`patch`) is small, array-shaped, runs every iteration. Lives in NumPy.
- The two are connected by `SystemTemplate`: a frozen numerical struct of arrays.
- Language choice for the solver is a per-function decision, not a per-stack decision.
  Cold path stays in Python; hot path can be ported to Numba/JAX later if and only
  if profiling demands it.
