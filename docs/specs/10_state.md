# 10 — Frontend State & Data Flow

**Status: TARGET.** The current code does **not** satisfy this spec. See
[§Known divergences](#known-divergences-current-bugs) for exactly where it differs.
This document is the acceptance criterion for the state-management refactor.

---

## The one rule

> **The store is the single source of truth. All writes go through one mutation path.
> Components never call `.set()` on a store directly, and never re-pull the backend
> themselves.**

Every confusing behavior in the first UI test traces back to violating this: three
components each re-implemented "mutate, then re-fetch, then `.set()`," and one data source
(fixtures) was wired in parallel to the real backend. Centralising writes removes the whole
class of "the view didn't update" bugs.

---

## Server-derived state, not client state

The backend owns the truth. The room is a *document* (`elements` + `modules` + routing)
held server-side; everything the UI shows is either that document or a **projection** of it
(`/assembly`: ownership, parameters, graph, problems). The frontend store is a **cache of
two server reads**, never an independent model the client mutates locally.

| Store        | Source              | Meaning                                                   |
| ------------ | ------------------- | --------------------------------------------------------- |
| `roomDoc`    | `GET …/document`    | raw elements + modules (+ routing)                        |
| `assembly`   | `GET …/assembly`    | derived projection: ownership, parameters, graph, problems|
| `registry`   | `GET /api/registry` | type schemas for forms (static for a session)             |
| `loading`    | —                   | any async op in flight                                    |
| `error`      | —                   | last fetch error (string \| null)                         |

Derived stores (`elements`, `modules`, `problems`) are read-only projections of the above.
There is **no** local element/module list the UI edits and later "saves."

## The mutation invariant

Per the API contract: *every mutation changes derived state, so after any mutation the
frontend re-pulls.* This is **not** each component's responsibility — it is the store's.

> **Invariant.** After any successful mutation, `roomDoc` **and** `assembly` are both
> re-pulled from the backend before the operation resolves. A component that issued a
> mutation can assume that, once its `await` returns, every store reflects the new state.

Re-pull **both**: a mutation to one (e.g. routing, a module write) changes the other's
projection (ownership, parameters, problems, graph). Pulling only `assembly` leaves the
element/module cards stale; pulling only `document` leaves the routing matrix and topology
stale. Either omission reproduces a "didn't update" bug.

`registry` is **not** re-pulled on mutation (type schemas don't change within a session).

## The single mutation path

All mutations funnel through one store action. Conceptually:

```js
// stores/model.js  (target shape)
async function applyMutation(apiCall) {
  return withLoading(async () => {
    const result = await apiCall();          // POST / PATCH / DELETE / PUT
    const [doc, asm] = await Promise.all([   // the invariant, in one place
      fetchDocument(),
      fetchAssembly(),
    ]);
    roomDoc.set(doc);
    assembly.set(asm);
    return result;                           // affected resource, for the caller
  });
}

// public, component-facing actions — thin wrappers:
export const addElement    = (type, fields) => applyMutation(() => createElement(type, fields));
export const editElement   = (eid, fields)  => applyMutation(() => updateElement(eid, fields));
export const removeElement = (eid)          => applyMutation(() => deleteElement(eid));
export const addModule     = (type, fields) => applyMutation(() => createModule(type, fields));
export const removeModule  = (mid)          => applyMutation(() => deleteModule(mid));
export const routeModule   = (mid, eids)    => applyMutation(() => setModuleRouting(mid, eids));
```

Components import these actions and `await` them. They **must not** import the raw `api.js`
mutators, and **must not** import `assembly.set` / `roomDoc.set`. That import boundary is
how the invariant is enforced mechanically rather than by discipline.

## Error handling

`applyMutation` runs inside `withLoading`, which sets `error` on failure and always clears
`loading`. On a failed mutation, **no store is `.set()`** — the cache stays consistent with
the last good server state (the failed write left the server unchanged, or we treat it as
such and the next successful re-pull reconciles). A component may still surface a *local*
form-level error for its modal; the global `error` store is for fetch/transport failures.

## Initial load

On app start, pull all three reads once (`refreshAll`): `document`, `assembly`, `registry`
in parallel. There is no "load the app, then click a button to populate it" step.

## Fixtures are an explicit, isolated mock — never a parallel data source

The dev convenience of running without a backend is legitimate, but it **must not** coexist
with live backend mutations. The split-brain failure happens when reads come from static
fixtures while writes go to a real backend whose state never matched those fixtures.

**Requirements:**

1. **One source per session.** Either the app talks to the real backend (reads *and*
   writes), or it runs against a mock — never reads from one and writes to the other.
2. **No silent auto-switch.** The fixture/mock path is selected by an explicit, visible
   mechanism (a build flag or a mocked `fetch` layer), not by silently swapping the data
   source inside the store based on `import.meta.env.DEV`.
3. **Preferred shape:** mock at the **transport** boundary (intercept `fetch` / use the
   Vite dev proxy to a stub), so the *same* store code and the *same* mutation path run in
   both modes. Fixtures then exercise the real data flow instead of bypassing it.
4. **No "Reload fixtures" button in the normal UI.** Re-pulling is what mutations already
   do. A manual "Refresh" (re-run `refreshAll`) is acceptable as a recovery affordance, but
   it is not part of the normal edit loop.

## Known divergences (current bugs)

The code as of this writing violates the spec in these specific ways. The refactor is "make
these false":

| # | Where | Current (wrong) | Target |
| - | ----- | --------------- | ------ |
| 1 | `stores/model.js` (`import.meta.env.DEV` branch) | Auto-loads static fixtures for **reads** while mutation handlers **write** to the real backend → split brain; "Reload fixtures" stomps backend state back to the static file. | One source per session; mock at the transport boundary; no auto-switch. |
| 2 | `ElementList.svelte`, `ModuleGraph.svelte` | Each mutation handler re-implements `await api(); Promise.all([fetchAssembly, fetchDocument]); store.set(...)` (5+ copies). Miss one and the view goes stale. | One `applyMutation()` in the store; components call thin actions and `await`. |
| 3 | components import `assembly as assemblyStore`, `roomDoc as docStore` and call `.set()` | Components hold write access to the cache. | Components import actions only; `.set()` is private to the store module. |

## Acceptance checklist

- [ ] Adding / editing / deleting an element updates the element cards **and** the routing
      matrix **and** the topology **and** the parameter table, with no manual refresh.
- [ ] Adding / deleting a module, and changing routing, do the same.
- [ ] No component imports raw `api.js` mutators or `*.set`.
- [ ] Removing the dev fixture path does not change any component's code (the mutation path
      is identical in mock and live modes).
- [ ] A failed mutation surfaces an error and leaves all stores consistent with the last
      good server state.
