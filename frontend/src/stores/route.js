/**
 * Lightweight hash-based client router for thnodes.
 *
 * Routes:
 *   #/             (or empty)  → home view  (model list)
 *   #/models/{uid}             → editor view for that uid
 *
 * The store derives state from window.location.hash and listens for the
 * native `hashchange` event, so the correct view survives a page refresh.
 * No router library is used.
 */

import { readable } from 'svelte/store';

/**
 * Parse a hash fragment into a route descriptor.
 * @param {string} hash  e.g. "#/models/abc123" or "" or "#/"
 * @returns {{ view: 'home'|'editor', uid: string|null }}
 */
function parseHash(hash) {
  // Normalise: strip leading '#'
  const path = hash.startsWith('#') ? hash.slice(1) : hash;

  const match = path.match(/^\/models\/([^/]+)$/);
  if (match) {
    return { view: 'editor', uid: match[1] };
  }
  return { view: 'home', uid: null };
}

/**
 * Readable store that reflects the current route.
 * Value shape: { view: 'home'|'editor', uid: string|null }
 */
export const route = readable(parseHash(window.location.hash), (set) => {
  function onHashChange() {
    set(parseHash(window.location.hash));
  }
  window.addEventListener('hashchange', onHashChange);
  return () => window.removeEventListener('hashchange', onHashChange);
});

/**
 * Navigate by pushing a new hash fragment.
 * Use '#/' for home and '#/models/{uid}' for the editor.
 *
 * @param {string} hash  e.g. '#/' or '#/models/abc123'
 */
export function navigate(hash) {
  window.location.hash = hash;
}
