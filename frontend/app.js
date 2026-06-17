// State fetched from API on load
let MATERIALS = [];   // [{key, name, lambda_W_mK, rho_kg_m3, cp_J_kgK, is_heavy}]
let SCHEMA = {};      // {element_types: [...], orientations: [...]}
let ALL_SIGNALS = []; // string[] from /api/signals

// In-memory room elements
let elements = [];
let elementIdSeq = 0;

function escAttr(s) {
  return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------

async function init() {
  try {
    const fetchJson = async url => {
      const r = await fetch(url);
      if (!r.ok) throw new Error(`${url}: ${r.status} ${r.statusText}`);
      return r.json();
    };
    const [schema, materials, signals] = await Promise.all([
      fetchJson("/api/schema"),
      fetchJson("/api/materials"),
      fetchJson("/api/signals").catch(() => []),
    ]);
    SCHEMA = schema;
    MATERIALS = materials;
    ALL_SIGNALS = signals;
  } catch (e) {
    setStatus(`Failed to load: ${e.message}`, true);
    return;
  }

  addElement();
  bindRoomFields();
  initDataSources();
  compute();
}

function bindRoomFields() {
  ["room-name", "room-floor", "room-height", "room-ach", "room-lat", "room-lon"]
    .forEach(id => document.getElementById(id).addEventListener("input", compute));
  document.getElementById("add-element-btn").addEventListener("click", () => {
    addElement();
    compute();
  });
}

// ---------------------------------------------------------------------------
// Element management
// ---------------------------------------------------------------------------

function addElement() {
  const id = elementIdSeq++;
  elements.push({
    id,
    name: `Element ${id + 1}`,
    type: SCHEMA.element_types?.[0]?.value ?? "wall",
    orientation: "S",
    area_m2: 10,
    u_value_override: null,
    layers: [{ material_key: "brick_common", thickness_m: 0.20 }],
  });
  renderElements();
}

function removeElement(id) {
  elements = elements.filter(e => e.id !== id);
  renderElements();
  compute();
}

function addLayer(elemId) {
  const el = elements.find(e => e.id === elemId);
  el.layers.push({ material_key: MATERIALS[0]?.key ?? "mineral_wool", thickness_m: 0.10 });
  renderElements();
  compute();
}

function removeLayer(elemId, layerIdx) {
  const el = elements.find(e => e.id === elemId);
  el.layers.splice(layerIdx, 1);
  renderElements();
  compute();
}

// ---------------------------------------------------------------------------
// Render element cards
// ---------------------------------------------------------------------------

function renderElements() {
  const list = document.getElementById("elements-list");
  const openIds = new Set(
    [...list.querySelectorAll(".element-card-body.open")].map(
      b => parseInt(b.closest("[data-id]")?.dataset.id)
    )
  );
  list.innerHTML = "";
  elements.forEach(el => {
    const wasOpen = openIds.size === 0 || openIds.has(el.id);
    list.appendChild(buildElementCard(el, wasOpen));
  });
}

function buildElementCard(el, isOpen = true) {
  const card = document.createElement("div");
  card.className = "card card-border bg-base-200 card-compact";
  card.dataset.id = el.id;

  // Header (toggle)
  const header = document.createElement("div");
  header.className = "card-title px-3 py-2 cursor-pointer select-none flex justify-between items-center text-sm hover:bg-base-300 rounded-t";
  const elNameSpan = document.createElement("span");
  elNameSpan.className = "el-name font-medium text-base-content";
  elNameSpan.textContent = el.name;
  const elMetaSpan = document.createElement("span");
  elMetaSpan.className = "el-meta text-xs text-base-content/40";
  elMetaSpan.textContent = `${el.type} · ${el.orientation} · ${el.area_m2} m²`;
  header.appendChild(elNameSpan);
  header.appendChild(elMetaSpan);

  const body = document.createElement("div");
  body.className = `element-card-body card-body pt-2${isOpen ? " open" : ""}`;

  header.addEventListener("click", () => body.classList.toggle("open"));

  // Main fields
  const fieldsHtml = `
    <div class="flex flex-col gap-1">
      <label class="flex items-center gap-2">
        <span class="text-xs text-base-content/50 w-24 shrink-0">Name</span>
        <input type="text" data-field="name" value="${escAttr(el.name)}"
               class="input input-xs input-bordered w-full" />
      </label>
      <label class="flex items-center gap-2">
        <span class="text-xs text-base-content/50 w-24 shrink-0">Type</span>
        <select data-field="type" class="select select-xs select-bordered w-full">
          ${SCHEMA.element_types.map(t =>
            `<option value="${t.value}" ${t.value === el.type ? "selected" : ""}>${t.label}</option>`
          ).join("")}
        </select>
      </label>
      <label class="flex items-center gap-2">
        <span class="text-xs text-base-content/50 w-24 shrink-0">Orientation</span>
        <select data-field="orientation" class="select select-xs select-bordered w-full">
          ${SCHEMA.orientations.map(o =>
            `<option value="${o.value}" ${o.value === el.orientation ? "selected" : ""}>${o.label}</option>`
          ).join("")}
        </select>
      </label>
      <label class="flex items-center gap-2">
        <span class="text-xs text-base-content/50 w-24 shrink-0">Area (m²)</span>
        <input type="number" data-field="area_m2" value="${el.area_m2}"
               class="input input-xs input-bordered w-full" />
      </label>
      <label class="flex items-center gap-2">
        <span class="text-xs text-base-content/50 w-24 shrink-0">U override</span>
        <input type="number" data-field="u_value_override" value="${el.u_value_override ?? ""}"
               placeholder="auto (W/m²K)" class="input input-xs input-bordered w-full" />
      </label>
    </div>
  `;
  body.innerHTML = fieldsHtml;

  // Layers section
  const layersSection = document.createElement("div");
  layersSection.className = "mt-3";
  layersSection.innerHTML = `<p class="text-xs uppercase tracking-widest text-base-content/30 mb-1">Layers (inside → outside)</p>`;

  const layerList = document.createElement("div");
  layerList.className = "flex flex-col gap-1";

  el.layers.forEach((layer, idx) => {
    const row = document.createElement("div");
    row.className = "grid gap-1 items-center";
    row.style.gridTemplateColumns = "1fr 72px 24px";
    row.innerHTML = `
      <select data-layer="${idx}" data-lfield="material_key"
              class="select select-xs select-bordered w-full">
        ${MATERIALS.map(m =>
          `<option value="${m.key}" ${m.key === layer.material_key ? "selected" : ""}>${m.name}</option>`
        ).join("")}
      </select>
      <input type="number" data-layer="${idx}" data-lfield="thickness_m"
             value="${layer.thickness_m}" placeholder="m"
             class="input input-xs input-bordered w-full" />
      <button class="btn btn-xs btn-ghost text-error px-1" data-remove-layer="${idx}">✕</button>
    `;
    layerList.appendChild(row);
  });

  layersSection.appendChild(layerList);

  const addLayerBtn = document.createElement("button");
  addLayerBtn.className = "btn btn-xs btn-ghost mt-1";
  addLayerBtn.textContent = "+ layer";
  addLayerBtn.addEventListener("click", () => addLayer(el.id));
  layersSection.appendChild(addLayerBtn);

  body.appendChild(layersSection);

  // Remove element
  const removeBtn = document.createElement("button");
  removeBtn.className = "btn btn-xs btn-ghost text-error mt-2";
  removeBtn.textContent = "remove element";
  removeBtn.addEventListener("click", () => removeElement(el.id));
  body.appendChild(removeBtn);

  // Wire field changes
  body.querySelectorAll("[data-field]").forEach(input => {
    input.addEventListener("input", () => {
      const field = input.dataset.field;
      el[field] = input.type === "number"
        ? (input.value === "" ? null : parseFloat(input.value))
        : input.value;
      header.querySelector(".el-name").textContent = el.name;
      header.querySelector(".el-meta").textContent = `${el.type} · ${el.orientation} · ${el.area_m2} m²`;
      compute();
    });
  });

  body.querySelectorAll("[data-layer]").forEach(input => {
    input.addEventListener("input", () => {
      const idx = parseInt(input.dataset.layer);
      const lfield = input.dataset.lfield;
      el.layers[idx][lfield] = lfield === "thickness_m" ? parseFloat(input.value) : input.value;
      compute();
    });
  });

  body.querySelectorAll("[data-remove-layer]").forEach(btn => {
    btn.addEventListener("click", () => removeLayer(el.id, parseInt(btn.dataset.removeLayer)));
  });

  card.appendChild(header);
  card.appendChild(body);
  return card;
}

// ---------------------------------------------------------------------------
// Build request payload
// ---------------------------------------------------------------------------

function buildRoom() {
  return {
    name:          document.getElementById("room-name").value,
    floor_area_m2: parseFloat(document.getElementById("room-floor").value),
    height_m:      parseFloat(document.getElementById("room-height").value),
    ach:           parseFloat(document.getElementById("room-ach").value),
    latitude:      parseFloat(document.getElementById("room-lat").value),
    longitude:     parseFloat(document.getElementById("room-lon").value),
    elements: elements.map(el => ({
      name:             el.name,
      type:             el.type,
      orientation:      el.orientation,
      area_m2:          el.area_m2,
      layers:           el.layers,
      u_value_override: el.u_value_override ?? null,
    })),
  };
}

// ---------------------------------------------------------------------------
// Compute & display
// ---------------------------------------------------------------------------

let _debounce = null;
function compute() {
  clearTimeout(_debounce);
  _debounce = setTimeout(_compute, 180);
}

async function _compute() {
  const room = buildRoom();
  if (!room.elements.length) return;

  setStatus("computing…", false);

  let data;
  try {
    const r = await fetch("/api/room/rc_model", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(room),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      setStatus(formatApiError(err), true);
      return;
    }
    data = await r.json();
  } catch (e) {
    setStatus(e.message, true);
    return;
  }

  setStatus("", false);
  renderPriors(data);
}

function setStatus(msg, isError) {
  const el = document.getElementById("status");
  el.textContent = msg;
  el.className = isError
    ? "text-xs text-error mb-2"
    : "text-xs text-base-content/30 mb-2";
}

function formatApiError(err) {
  if (err.detail && Array.isArray(err.detail)) {
    return err.detail.map(d => d.msg).join("; ");
  }
  return JSON.stringify(err);
}

// ---------------------------------------------------------------------------
// Prior display
// ---------------------------------------------------------------------------

const PARAM_ORDER = ["H_env", "H_ve", "C_wall", "C_room", "alpha_eff"];

function renderPriors(data) {
  const container = document.getElementById("priors-content");
  container.innerHTML = "";
  PARAM_ORDER.forEach(key => {
    if (data[key]) container.appendChild(buildPriorBlock(key, data[key]));
  });
}

function buildPriorBlock(key, p) {
  const block = document.createElement("div");

  const [mu, sigma, unit] = scaleUnits(p.mu, p.sigma, p.unit);

  // Header
  const header = document.createElement("div");
  header.className = "flex items-baseline gap-2 mb-1";
  header.innerHTML = `
    <span class="text-info font-semibold">${p.symbol}</span>
    <span class="text-xs text-base-content/40">${p.name}</span>
    <span class="badge badge-xs badge-ghost">${unit}</span>
  `;
  block.appendChild(header);

  // Contributions
  const maxVal = Math.max(
    ...p.contributions.map(c => Math.abs(scaleUnits(c.value, c.sigma, p.unit)[0])),
    1e-9
  );

  p.contributions.forEach(c => {
    const [cVal, cSig] = scaleUnits(c.value, c.sigma, p.unit);
    const barPct = Math.min(100, Math.abs(cVal) / maxVal * 100);

    const row = document.createElement("div");
    row.className = "grid items-center gap-2 py-0.5 text-xs text-base-content/50";
    row.style.gridTemplateColumns = "1fr 100px 80px";
    const labelSpan = document.createElement("span");
    labelSpan.textContent = c.label ?? "";
    if (c.detail != null) labelSpan.setAttribute("title", c.detail);
    const sigStr = c.sigma != null ? `±${fmt(cSig)}` : "";
    row.innerHTML = `
      <span></span>
      <span class="text-right tabular-nums">
        +${fmt(cVal)} <span class="text-base-content/30">${sigStr}</span>
      </span>
      <div class="contrib-bar-wrap">
        <div class="contrib-bar" style="width:${barPct.toFixed(1)}%"></div>
      </div>
    `;
    row.replaceChild(labelSpan, row.firstElementChild);
    block.appendChild(row);
  });

  // Total row
  const cv = mu > 0 ? (sigma / mu * 100).toFixed(0) : "—";
  const total = document.createElement("div");
  total.className = "flex items-center gap-3 border-t border-base-300 pt-1 mt-0.5 text-sm";
  total.innerHTML = `
    <span class="tabular-nums font-medium">= ${fmt(mu)} ${unit}</span>
    <span class="text-xs text-base-content/40 tabular-nums">± ${fmt(sigma)}</span>
    <span class="badge badge-xs badge-ghost text-base-content/30">CV ${cv}%</span>
  `;
  block.appendChild(total);

  return block;
}

function scaleUnits(mu, sigma, unit) {
  if (unit === "MJ/K") return [mu / 1e6, sigma / 1e6, "MJ/K"];
  return [mu, sigma, unit];
}

function fmt(v) {
  if (Math.abs(v) >= 100) return v.toFixed(1);
  if (Math.abs(v) >= 10)  return v.toFixed(2);
  return v.toFixed(3);
}

// ---------------------------------------------------------------------------
// Data sources
// ---------------------------------------------------------------------------

const DATA_SOURCE_DEFS = [
  { key: "T_int", label: "T_int", hint: "indoor temperature" },
  { key: "T_ext", label: "T_ext", hint: "outdoor temperature" },
  { key: "Q_sol", label: "Q_sol", hint: "solar irradiance" },
];

// selected signal per key, null = not set
const dataSources = Object.fromEntries(DATA_SOURCE_DEFS.map(d => [d.key, null]));

let _pickerTarget = null; // key being picked

function initDataSources() {
  renderDataSources();
  initSignalModal();
}

function renderDataSources() {
  const list = document.getElementById("data-sources-list");
  list.innerHTML = "";
  DATA_SOURCE_DEFS.forEach(def => {
    const selected = dataSources[def.key];
    const row = document.createElement("div");
    row.className = "flex items-center gap-2 text-xs";
    row.innerHTML = `
      <span class="text-base-content/50 w-12 shrink-0 font-mono">${escAttr(def.label)}</span>
      <span class="flex-1 truncate text-base-content/40 italic" title="${escAttr(selected ?? "")}"
            data-ds-value="${escAttr(def.key)}">${selected ? escAttr(selected) : `<span class="text-base-content/20">${escAttr(def.hint)}</span>`}</span>
      <button class="btn btn-xs btn-ghost px-1" data-ds-pick="${escAttr(def.key)}">pick</button>
    `;
    list.appendChild(row);
  });

  list.querySelectorAll("[data-ds-pick]").forEach(btn => {
    btn.addEventListener("click", () => openSignalPicker(btn.dataset.dsPick));
  });
}

function initSignalModal() {
  const modal = document.getElementById("signal-modal");
  const search = document.getElementById("signal-search");

  search.addEventListener("input", () => renderSignalList(search.value.trim()));

  document.getElementById("signal-modal-clear").addEventListener("click", () => {
    if (_pickerTarget) {
      dataSources[_pickerTarget] = null;
      renderDataSources();
    }
    modal.close();
  });
}

function openSignalPicker(key) {
  _pickerTarget = key;
  const def = DATA_SOURCE_DEFS.find(d => d.key === key);
  document.getElementById("signal-modal-title").textContent = `Pick signal for ${def.label} — ${def.hint}`;
  document.getElementById("signal-search").value = "";
  renderSignalList("");
  document.getElementById("signal-modal").showModal();
}

function renderSignalList(filter) {
  const container = document.getElementById("signal-list");
  container.innerHTML = "";

  const lc = filter.toLowerCase();
  const shown = ALL_SIGNALS.filter(s => !lc || s.toLowerCase().includes(lc));

  if (!shown.length) {
    container.innerHTML = `<p class="text-xs text-base-content/30 p-2">${ALL_SIGNALS.length ? "no match" : "no signals available (InfluxDB unreachable?)"}</p>`;
    return;
  }

  shown.forEach(sig => {
    const btn = document.createElement("button");
    btn.className = "btn btn-xs btn-ghost justify-start font-mono text-left" +
      (dataSources[_pickerTarget] === sig ? " btn-active" : "");
    btn.textContent = sig;
    btn.addEventListener("click", () => {
      dataSources[_pickerTarget] = sig;
      renderDataSources();
      document.getElementById("signal-modal").close();
    });
    container.appendChild(btn);
  });
}

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------

init();
