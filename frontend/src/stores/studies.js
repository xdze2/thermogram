/**
 * Studies store for thnodes.
 *
 * Studies are a SEPARATE data layer from the model document. They do NOT
 * participate in the applyMutation → re-pull document+assembly invariant
 * (see spec 50_studies.md §"Frontend state" and stores/model.js).
 *
 * Mutations update `studies` and `activeStudy` in place. Callers are
 * responsible for showing errors (actions throw on failure).
 */

import { writable } from 'svelte/store';
import {
  fetchStudies,
  createStudy,
  patchStudy,
  deleteStudy,
  clearStudyResults,
  runStudySimulate,
} from '../lib/api.js';

/** @type {import('svelte/store').Writable<import('../lib/api.js').Study[]>} */
export const studies = writable([]);

/** @type {import('svelte/store').Writable<object|null>} */
export const activeStudy = writable(null);

// ---------------------------------------------------------------------------
// Internal helper: replace a study in the studies array in place.
// If the updated study matches activeStudy, update that too.
// ---------------------------------------------------------------------------

function replaceStudy(updated) {
  studies.update((list) =>
    list.map((s) => (s.uid === updated.uid ? updated : s))
  );
  activeStudy.update((current) =>
    current?.uid === updated.uid ? updated : current
  );
}

// ---------------------------------------------------------------------------
// Public actions — all throw on failure so callers can display errors.
// ---------------------------------------------------------------------------

/**
 * Fetch and replace all studies for the given model.
 * Called by model.js refreshAll() when the editor opens.
 *
 * @param {string} modelId
 */
export async function loadStudies(modelId) {
  const list = await fetchStudies(modelId);
  studies.set(list);
  // If the current activeStudy belongs to a different model, clear it.
  activeStudy.update((current) => {
    if (!current) return null;
    const still = list.find((s) => s.uid === current.uid);
    return still ?? null;
  });
}

/**
 * Create a new study and select it as the active study.
 *
 * @param {string} modelId
 * @param {object} [body]  Optional creation fields (name, time_range, …)
 * @returns {object} The created Study.
 */
export async function addStudy(modelId, body = {}) {
  const created = await createStudy(modelId, body);
  studies.update((list) => [...list, created]);
  activeStudy.set(created);
  return created;
}

/**
 * Patch author-controlled fields (name, time_range, signal_overrides, params).
 * Does NOT touch results.
 *
 * @param {string} modelId
 * @param {string} studyId
 * @param {object} body  Partial Study fields to update.
 * @returns {object} The updated Study.
 */
export async function updateStudy(modelId, studyId, body) {
  const updated = await patchStudy(modelId, studyId, body);
  replaceStudy(updated);
  return updated;
}

/**
 * Delete a study. If it was the active study, clears activeStudy.
 *
 * @param {string} modelId
 * @param {string} studyId
 */
export async function removeStudy(modelId, studyId) {
  await deleteStudy(modelId, studyId);
  studies.update((list) => list.filter((s) => s.uid !== studyId));
  activeStudy.update((current) => (current?.uid === studyId ? null : current));
}

/**
 * Clear results.simulate and results.fit on a study (DELETE …/results).
 *
 * @param {string} modelId
 * @param {string} studyId
 * @returns {object} The updated Study (results nulled).
 */
export async function clearResults(modelId, studyId) {
  const updated = await clearStudyResults(modelId, studyId);
  replaceStudy(updated);
  return updated;
}

/**
 * Run the forward simulation for a study. Writes results.simulate.
 *
 * @param {string} modelId
 * @param {string} studyId
 * @param {object} [body]  Optional { x0: number[] }
 * @returns {object} The updated Study (results.simulate populated).
 */
export async function runSimulate(modelId, studyId, body = {}) {
  const updated = await runStudySimulate(modelId, studyId, body);
  replaceStudy(updated);
  return updated;
}
