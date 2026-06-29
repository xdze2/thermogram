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
 * In development (import.meta.env.DEV), loadFixtures() is called automatically
 * so the UI works without a running backend.
 */

import { writable, derived } from 'svelte/store';
import { fetchAssembly, fetchDocument, fetchRegistry } from '../lib/api.js';

// ---------------------------------------------------------------------------
// Core writable stores
// ---------------------------------------------------------------------------

export const assembly = writable(null);
export const roomDoc  = writable(null);
export const registry = writable(null);
export const error    = writable(null);
export const loading  = writable(false);

// ---------------------------------------------------------------------------
// Derived: flat element / module lists
// ---------------------------------------------------------------------------

export const elements = derived(roomDoc, ($doc) => $doc?.elements ?? []);
export const modules  = derived(roomDoc, ($doc) => $doc?.modules ?? []);
export const problems = derived(assembly, ($asm) => $asm?.problems ?? []);

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
// Data-fetching actions
// ---------------------------------------------------------------------------

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

export async function refreshAssembly() {
  await withLoading(async () => {
    const asm = await fetchAssembly();
    assembly.set(asm);
  });
}

export async function refreshDocument() {
  await withLoading(async () => {
    const doc = await fetchDocument();
    roomDoc.set(doc);
  });
}

export async function fetchAssemblyStore() {
  return refreshAssembly();
}

export async function fetchRegistryStore() {
  await withLoading(async () => {
    const reg = await fetchRegistry();
    registry.set(reg);
  });
}

// ---------------------------------------------------------------------------
// Fixture loader (development mode — no backend required)
// ---------------------------------------------------------------------------

export async function loadFixtures() {
  loading.set(true);
  error.set(null);
  try {
    const [asm, doc, reg] = await Promise.all([
      import('../fixtures/assembly.json'),
      import('../fixtures/document.json'),
      import('../fixtures/registry.json'),
    ]);
    assembly.set(asm.default);
    roomDoc.set(doc.default);
    registry.set(reg.default);
  } catch (err) {
    error.set(err.message ?? String(err));
  } finally {
    loading.set(false);
  }
}

// ---------------------------------------------------------------------------
// Auto-init: use fixtures in dev, real API in production
// ---------------------------------------------------------------------------

if (import.meta.env.DEV) {
  loadFixtures();
} else {
  refreshAll();
}
