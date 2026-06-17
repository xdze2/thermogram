import { writable, derived, get } from 'svelte/store';

// --- Router (hash-based) ---
// Routes: '' → studies list, 'study/:id' → study editor

function parseHash(hash) {
  const h = hash.replace(/^#\/?/, '');
  if (!h) return { page: 'list' };
  const m = h.match(/^study\/([a-f0-9]+)$/);
  if (m) return { page: 'study', id: m[1] };
  return { page: 'list' };
}

export const route = writable(parseHash(window.location.hash));

window.addEventListener('hashchange', () => {
  route.set(parseHash(window.location.hash));
});

export function navigate(path) {
  window.location.hash = path ? `/${path}` : '';
}

// --- API data fetched on init ---
export const materials = writable([]);
export const schema = writable({ element_types: [], orientations: [] });
export const allSignals = writable([]);

// --- Room fields ---
export const room = writable({
  name: 'My room',
  floor_area_m2: 20,
  height_m: 2.5,
  ach: 0.5,
  latitude: 48.85,
  longitude: 2.35,
});

// --- Envelope elements ---
let _idSeq = 0;
export const elements = writable([]);

export function nextId() { return _idSeq++; }

export function addElement() {
  const s = get(schema);
  const m = get(materials);
  const id = nextId();
  elements.update(els => [...els, {
    id,
    name: `Element ${id + 1}`,
    type: s.element_types?.[0]?.value ?? 'wall',
    orientation: 'S',
    area_m2: 10,
    u_value_override: null,
    layers: [{ material_key: m[0]?.key ?? 'brick_common', thickness_m: 0.20 }],
  }]);
}

export function removeElement(id) {
  elements.update(els => els.filter(e => e.id !== id));
}

export function updateElement(id, patch) {
  elements.update(els => els.map(e => e.id === id ? { ...e, ...patch } : e));
}

export function addLayer(elemId) {
  const m = get(materials);
  elements.update(els => els.map(e => {
    if (e.id !== elemId) return e;
    return { ...e, layers: [...e.layers, { material_key: m[0]?.key ?? 'mineral_wool', thickness_m: 0.10 }] };
  }));
}

export function removeLayer(elemId, idx) {
  elements.update(els => els.map(e => {
    if (e.id !== elemId) return e;
    const layers = e.layers.filter((_, i) => i !== idx);
    return { ...e, layers };
  }));
}

export function updateLayer(elemId, idx, patch) {
  elements.update(els => els.map(e => {
    if (e.id !== elemId) return e;
    const layers = e.layers.map((l, i) => i === idx ? { ...l, ...patch } : l);
    return { ...e, layers };
  }));
}

// --- Data sources ---
export const DATA_SOURCE_DEFS = [
  { key: 'T_int',    label: 'T_int',   hint: 'indoor temperature' },
  { key: 'T_ext',    label: 'T_ext',   hint: 'outdoor temperature' },
  { key: 'GHI',      label: 'GHI',     hint: 'global horizontal irradiance' },
  { key: 'direct',   label: 'direct',  hint: 'direct (beam) horizontal irradiance' },
  { key: 'diffuse',  label: 'diffuse', hint: 'diffuse horizontal irradiance' },
];

export const dataSources = writable({ T_int: null, T_ext: null, GHI: null, direct: null, diffuse: null });

// --- Time range ---
function todayISO() { return new Date().toISOString().slice(0, 10); }
function addDays(iso, n) {
  const [y, m, d] = iso.split('-').map(Number);
  const date = new Date(y, m - 1, d + n);
  return date.toLocaleDateString('en-CA'); // YYYY-MM-DD in local time
}
const today = todayISO();
export const rangeStart = writable(addDays(today, -7));
export const rangeEnd = writable(today);
export { todayISO, addDays };

// --- RC priors result ---
export const rcResult = writable(null);
export const rcStatus = writable('');
export const rcError = writable(false);

// --- Theme ---
export const theme = writable(localStorage.getItem('theme') ?? 'dark');

// --- Persistence ---
const STORAGE_KEY = 'thnodes_state';

export function saveState() {
  const state = {
    room: get(room),
    elements: get(elements),
    _idSeq,
    dataSources: get(dataSources),
    rangeStart: get(rangeStart),
    rangeEnd: get(rangeEnd),
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

export function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

export function restoreState(saved) {
  if (!saved) return false;
  if (saved.room) room.set(saved.room);
  if (saved.elements?.length) {
    elements.set(saved.elements);
    _idSeq = Math.max(_idSeq, ...(saved.elements.map(e => e.id + 1)));
  }
  if (saved.dataSources) dataSources.set(saved.dataSources);
  if (saved.rangeStart) rangeStart.set(saved.rangeStart);
  if (saved.rangeEnd) rangeEnd.set(saved.rangeEnd);
  return true;
}
