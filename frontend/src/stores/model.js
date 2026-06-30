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
  putSignalBinding,
  createSensor,
  deleteSensor,
  putSensorBinding,
  getModelId,
} from '../lib/api.js';
import { loadStudies } from './studies.js';

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
export const sensors         = derived(roomDoc, ($doc) => $doc?.sensors ?? []);
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

export const addSensor        = (state, name)         => applyMutation(() => createSensor(state, name));
export const removeSensor     = (sensorId)            => applyMutation(() => deleteSensor(sensorId));
export const setSensorBinding = (sensorId, binding)   => applyMutation(() => putSensorBinding(sensorId, binding));

/**
 * Set (string) or clear (null) the InfluxDB binding for a required signal.
 * Follows the mutation invariant: re-pulls both roomDoc and assembly so
 * required_signals[] in the assembly store reflects the new binding state.
 *
 * @param {string} signalName  - The signal's name field (e.g. "T_ext")
 * @param {string|null} binding - InfluxDB query string or null to clear
 */
export const setSignalBinding = (signalName, binding) =>
  applyMutation(() => putSignalBinding(signalName, binding));

// ---------------------------------------------------------------------------
// Read actions (non-mutating)
// ---------------------------------------------------------------------------

/**
 * Pull document, assembly, registry, and studies in parallel.
 * Called when the editor opens a model (see App.svelte $effect).
 * Studies failures are silenced into console warnings so a missing studies
 * endpoint (backend not yet built) does not break the existing editor flow.
 */
export async function refreshAll() {
  await withLoading(async () => {
    const modelId = getModelId();
    const [asm, doc, reg] = await Promise.all([
      fetchAssembly(),
      fetchDocument(),
      fetchRegistry(),
    ]);
    assembly.set(asm);
    roomDoc.set(doc);
    registry.set(reg);

    // Studies are a separate data layer — failures must not propagate to the
    // shared `error` store and must not interrupt the document/assembly refresh.
    loadStudies(modelId).catch((err) => {
      console.warn('[studies] loadStudies failed during refreshAll:', err.message ?? err);
    });
  });
}
