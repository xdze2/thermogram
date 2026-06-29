/**
 * Centralized API client for the thnodes FastAPI backend.
 * All endpoints are relative to /api/models/default/ unless noted.
 *
 * In development mode, fixture JSON is loaded instead (see stores/model.js).
 * In production, these functions call the real backend.
 */

const MODEL_ID = 'default';
const BASE = `/api/models/${MODEL_ID}`;

/** Generic fetch wrapper that throws a structured error on non-2xx. */
async function apiFetch(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch (_) {
      // response body is not JSON — keep the status string
    }
    throw new Error(detail);
  }

  // 204 No Content has no body
  if (res.status === 204) return null;
  return res.json();
}

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

export function fetchRegistry() {
  return apiFetch('/api/registry');
}

// ---------------------------------------------------------------------------
// Document (raw room doc: elements + modules)
// ---------------------------------------------------------------------------

export function fetchDocument() {
  return apiFetch(`${BASE}/document`);
}

// ---------------------------------------------------------------------------
// Assembly (derived projection — refresh after every mutation)
// ---------------------------------------------------------------------------

export function fetchAssembly() {
  return apiFetch(`${BASE}/assembly`);
}

// ---------------------------------------------------------------------------
// Element CRUD
// ---------------------------------------------------------------------------

export function createElement(type, fields) {
  return apiFetch(`${BASE}/elements`, {
    method: 'POST',
    body: JSON.stringify({ type, fields }),
  });
}

export function updateElement(eid, fields) {
  return apiFetch(`${BASE}/elements/${eid}`, {
    method: 'PATCH',
    body: JSON.stringify({ fields }),
  });
}

export function deleteElement(eid) {
  return apiFetch(`${BASE}/elements/${eid}`, { method: 'DELETE' });
}

// ---------------------------------------------------------------------------
// Module CRUD
// ---------------------------------------------------------------------------

export function createModule(type, fields = {}) {
  return apiFetch(`${BASE}/modules`, {
    method: 'POST',
    body: JSON.stringify({ type, fields }),
  });
}

export function deleteModule(mid) {
  return apiFetch(`${BASE}/modules/${mid}`, { method: 'DELETE' });
}

export function setModuleRouting(mid, element_ids) {
  return apiFetch(`${BASE}/modules/${mid}/routing`, {
    method: 'PUT',
    body: JSON.stringify({ element_ids }),
  });
}

// ---------------------------------------------------------------------------
// Physics views
// ---------------------------------------------------------------------------

export function runSimulate(signals, x0, params = null, dt = 3600.0) {
  const body = { signals, x0, dt };
  if (params) body.params = params;
  return apiFetch(`${BASE}/simulate`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function fetchIdentifiability() {
  return apiFetch(`${BASE}/identifiability`);
}

/** Returns the URL for the server-rendered topology SVG. */
export function topologySvgUrl() {
  return `${BASE}/topology.svg`;
}
