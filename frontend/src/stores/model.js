/**
 * Shared application store for thnodes.
 *
 * Holds:
 *   - assembly  : GET /assembly response (ownership, parameters, graph, problems, …)
 *   - roomDoc   : GET /document response (raw elements + modules)
 *   - registry  : GET /registry response (type schemas for forms)
 *   - error     : last fetch error message (string | null)
 *   - loading   : whether any async operation is in flight (boolean)
 *
 * Exports `roomDoc` (not `document`) to avoid shadowing the browser global.
 *
 * THE ONE RULE: All writes go through applyMutation(). Components never call
 * .set() on assembly or roomDoc directly. The store is the single source of truth.
 *
 * Fixture / mock-backend support lives entirely in src/lib/mockServer.js and
 * src/main.js (enabled by VITE_USE_FIXTURES=true). This file is unaware of it.
 */

import { writable, derived } from 'svelte/store';
import {
  fetchAssembly,
  fetchDocument,
  fetchRegistry,
  createElement,
  updateElement,
  deleteElement,
} from '../lib/api.js';

// ---------------------------------------------------------------------------
// Core writable stores (private write surface — .set() only called here)
// ---------------------------------------------------------------------------

export const assembly = writable(null);
export const roomDoc  = writable(null);
export const registry = writable(null);
export const error    = writable(null);
export const loading  = writable(false);

// ---------------------------------------------------------------------------
// Derived: flat element / module lists and problem list
// ---------------------------------------------------------------------------

export const elements        = derived(roomDoc, ($doc) => $doc?.elements ?? []);
export const modules         = derived(roomDoc, ($doc) => $doc?.modules ?? []);
export const signals         = derived(roomDoc, ($doc) => $doc?.signals ?? []);
export const problems        = derived(assembly, ($asm) => $asm?.problems ?? []);
export const requiredSignals = derived(assembly, ($asm) => $asm?.required_signals ?? []);

// ---------------------------------------------------------------------------
// Internal helper: wrap async call with loading + error state
// ---------------------------------------------------------------------------

async function withLoading(fn) {
  loading.set(true);
  error.set(null);
  try {
    return await fn();
  } catch (err) {
    error.set(err.message ?? String(err));
    throw err;
  } finally {
    loading.set(false);
  }
}

// ---------------------------------------------------------------------------
// Single mutation path
//
// Every write goes here. After any successful mutation, BOTH roomDoc and
// assembly are re-pulled so all derived views are consistent. On failure,
// neither store is touched — the cache stays at the last good server state.
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Public, component-facing mutation actions (thin wrappers over applyMutation)
// ---------------------------------------------------------------------------

export const addElement    = (type, fields) => applyMutation(() => createElement(type, fields));
export const editElement   = (eid, fields)  => applyMutation(() => updateElement(eid, fields));
export const removeElement = (eid)          => applyMutation(() => deleteElement(eid));

// ---------------------------------------------------------------------------
// Read actions (non-mutating)
// ---------------------------------------------------------------------------

/** Pull all three reads in parallel. Called once on app start from main.js. */
export async function refreshAll() {
  await withLoading(async () => {
    const [asm, doc, reg] = await Promise.all([
      fetchAssembly(),
      fetchDocument(),
      fetchRegistry(),
    ]);
    assembly.set(asm);
    roomDoc.set(doc);
    registry.set(reg);
  });
}
