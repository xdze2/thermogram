<script>
  import { onMount } from 'svelte';
  import SignalPicker from '$lib/SignalPicker.svelte';

  let { house, onchange, customMaterials = {}, rcModel = null, dirty = false, saveLoading = false, saveError = null, onsave = null, ondelete = null } = $props();

  let addMenuOpen = $state(false);

  function clickOutside(node) {
    const handler = (e) => { if (!node.contains(e.target)) addMenuOpen = false; };
    document.addEventListener('mousedown', handler, true);
    return { destroy() { document.removeEventListener('mousedown', handler, true); } };
  }

  // ── signals autocomplete ──────────────────────────────────────────────────
  const API = 'http://localhost:8001';
  let signals = $state([]);

  onMount(async () => {
    try {
      const res = await fetch(`${API}/signals`);
      if (res.ok) signals = await res.json();
    } catch { /* offline — autocomplete simply stays empty */ }
  });

  const BUILTIN_MATERIALS = {
    brick_full:     { lambda: 0.8,   rho: 1800, cp: 840,  name: 'Brique pleine' },
    brick_hollow:   { lambda: 0.45,  rho: 1200, cp: 840,  name: 'Brique creuse' },
    stone_calcaire: { lambda: 1.7,   rho: 2200, cp: 900,  name: 'Calcaire' },
    stone_rubble:   { lambda: 1.3,   rho: 2000, cp: 900,  name: 'Moellon' },
    concrete_heavy: { lambda: 1.75,  rho: 2300, cp: 840,  name: 'Béton lourd' },
    concrete_slab:  { lambda: 1.65,  rho: 2200, cp: 840,  name: 'Dalle béton' },
    glass_wool:     { lambda: 0.035, rho: 15,   cp: 840,  name: 'Laine de verre' },
    rock_wool:      { lambda: 0.038, rho: 30,   cp: 840,  name: 'Laine de roche' },
    cellulose:      { lambda: 0.040, rho: 50,   cp: 1900, name: 'Ouate de cellulose' },
    plaster:        { lambda: 0.57,  rho: 1200, cp: 1000, name: 'Plâtre' },
    lime_plaster:   { lambda: 0.87,  rho: 1600, cp: 1000, name: 'Enduit chaux' },
    wood_frame:     { lambda: 0.13,  rho: 530,  cp: 1600, name: 'Bois (structure)' },
    wood_floor:     { lambda: 0.16,  rho: 700,  cp: 1600, name: 'Parquet' },
    tile_clay:      { lambda: 1.0,   rho: 1900, cp: 840,  name: 'Tuile terre cuite' },
  };

  const ORIENTATIONS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
  const BOUNDARY_KINDS = ['outdoor', 'ground'];

  // ── derived ───────────────────────────────────────────────────────────────
  const rooms      = $derived(house?.rooms    ?? []);
  const elements   = $derived(house?.elements ?? []);
  const materials  = $derived({ ...BUILTIN_MATERIALS, ...(customMaterials ?? {}), ...(house?.materials ?? {}) });
  const wallChains = $derived(rcModel?.wall_chains ?? {});

  // All zone options: rooms + boundary elements (outdoor, ground)
  const zoneOptions = $derived([
    ...rooms.map(r => ({ id: r.id, label: r.label || '(room)' })),
    ...elements
      .filter(e => BOUNDARY_KINDS.includes(e.kind))
      .map(e => ({ id: e.id, label: e.label || e.kind })),
  ]);

  function zoneLabel(id) {
    const z = zoneOptions.find(z => z.id === id);
    return z ? z.label : id.slice(0, 8) + '…';
  }

  // ── key figures (client-side computed) ───────────────────────────────────
  function roomVolume(r) {
    return (r.a ?? 0) * (r.b ?? 0) * (r.c ?? 0);
  }

  function opaqueUA(el) {
    const area = (el.a ?? 0) * (el.b ?? 0);
    const R = (el.layers ?? []).reduce((acc, l) => {
      const mat = materials[l.material];
      return acc + (mat ? (l.thickness / mat.lambda) : 0);
    }, 0.13 + 0.04); // h_i + h_e defaults
    return R > 0 ? area / R : null;
  }

  // R value (m²·K/W) per layer and total — for display in the stack description
  function opaqueLayerR(layer) {
    const mat = materials[layer.material];
    return mat ? layer.thickness / mat.lambda : null;
  }

  function opaqueTotalR(el) {
    const h_i = el.h_i ?? 7.7;
    const h_e = el.h_e ?? 25.0;
    const R_layers = (el.layers ?? []).reduce((acc, l) => {
      const r = opaqueLayerR(l);
      return acc + (r ?? 0);
    }, 0);
    return (1 / h_i) + R_layers + (1 / h_e);
  }

  function keyFigures(item) {
    if (item._type === 'room') {
      const vol = roomVolume(item);
      return vol > 0 ? `${vol.toFixed(0)} m³` : null;
    }
    if (item.kind === 'opaque') {
      const area = (item.a ?? 0) * (item.b ?? 0);
      const R = opaqueTotalR(item);
      const chainN = wallChains[item.label]?.chain_n;
      const chainBadge = item.no_mass ? ' [R]' : (chainN != null && chainN > 1 ? ` ×${chainN}` : '');
      return R > 0 ? `${area.toFixed(0)} m² · R ${R.toFixed(2)} m²K/W${chainBadge}` : `${area.toFixed(0)} m²${chainBadge}`;
    }
    if (item.kind === 'glazing') {
      const area = (item.a ?? 0) * (item.b ?? 0);
      const ua = item.U != null ? item.U * area : null;
      return ua != null ? `${area.toFixed(1)} m² · ${ua.toFixed(1)} W/K` : `${area.toFixed(1)} m²`;
    }
    if (item.kind === 'air_exchange') {
      return item.ach != null ? `${item.ach} ACH` : null;
    }
    if (item.kind === 'outdoor') {
      return item.location?.label ?? null;
    }
    return null;
  }

  // ── patch helpers ─────────────────────────────────────────────────────────
  function patchHouse(patch) {
    onchange({ ...house, ...patch });
  }

  function applyPatch(obj, patch) {
    const result = { ...obj };
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined) delete result[k];
      else result[k] = v;
    }
    return result;
  }

  function patchRoom(id, patch) {
    patchHouse({ rooms: rooms.map(r => r.id === id ? applyPatch(r, patch) : r) });
  }

  function patchElement(id, patch) {
    patchHouse({ elements: elements.map(el => el.id === id ? applyPatch(el, patch) : el) });
  }

  function deleteRoom(id) {
    patchHouse({
      rooms:    rooms.filter(r => r.id !== id),
      elements: elements.filter(el => !el.between?.includes(id)),
    });
  }

  function deleteElement(id) {
    patchHouse({ elements: elements.filter(el => el.id !== id) });
  }

  // ── layer helpers ─────────────────────────────────────────────────────────
  function patchLayer(elId, idx, patch) {
    patchHouse({ elements: elements.map(el => {
      if (el.id !== elId) return el;
      return { ...el, layers: el.layers.map((l, i) => i === idx ? { ...l, ...patch } : l) };
    })});
  }

  function addLayer(elId) {
    patchHouse({ elements: elements.map(el => {
      if (el.id !== elId) return el;
      return { ...el, layers: [...el.layers, { material: 'plaster', thickness: 0.01 }] };
    })});
  }

  function deleteLayer(elId, idx) {
    patchHouse({ elements: elements.map(el => {
      if (el.id !== elId) return el;
      return { ...el, layers: el.layers.filter((_, i) => i !== idx) };
    })});
  }

  // ── expanded row ──────────────────────────────────────────────────────────
  let expandedId = $state(null);

  function toggleExpand(id) {
    expandedId = expandedId === id ? null : id;
  }

  // ── add helpers: create skeleton + expand immediately ─────────────────────
  function addRoom() {
    const id = crypto.randomUUID();
    const defaultZone = zoneOptions.find(z => BOUNDARY_KINDS.includes(
      elements.find(e => e.id === z.id)?.kind
    ));
    patchHouse({ rooms: [...rooms, { id, label: '', role: 'mass', a: 4, b: 4, c: 2.5 }] });
    expandedId = id;
  }

  function addElement(kind) {
    const id = crypto.randomUUID();
    const firstRoom = rooms[0]?.id ?? '';
    const firstBoundary = elements.find(e => BOUNDARY_KINDS.includes(e.kind))?.id ?? '';
    let el;
    if (kind === 'opaque') {
      el = { id, kind, label: '', between: [firstRoom, firstBoundary],
             a: 4, b: 2.5, orientation: 'S', tilt: 90,
             layers: [{ material: 'brick_full', thickness: 0.2 }] };
    } else if (kind === 'glazing') {
      el = { id, kind, label: '', between: [firstRoom, firstBoundary],
             a: 1.2, b: 1.4, orientation: 'S', tilt: 90,
             U: 2.8, SHGC: 0.67 };
    } else if (kind === 'air_exchange') {
      el = { id, kind, label: '', between: [firstRoom, firstBoundary], ach: 0.4 };
    } else if (kind === 'outdoor') {
      el = { id, kind, label: '', location: { lat: 48.85, lon: 2.35, label: 'Paris' } };
    } else if (kind === 'ground') {
      el = { id, kind, label: '' };
    }
    patchHouse({ elements: [...elements, el] });
    expandedId = id;
  }

  // ── flat ordered list ─────────────────────────────────────────────────────
  const flatItems = $derived([
    ...rooms.map(r => ({ _type: 'room', ...r })),
    ...elements.filter(e => !BOUNDARY_KINDS.includes(e.kind)),
    ...elements.filter(e => BOUNDARY_KINDS.includes(e.kind)),
  ]);

  // ── kind metadata ─────────────────────────────────────────────────────────
  const KIND_META = {
    room:         { icon: '⬜', label: 'room',     color: 'room' },
    opaque:       { icon: '▬',  label: 'wall',     color: 'opaque' },
    glazing:      { icon: '◻',  label: 'window',   color: 'glazing' },
    air_exchange: { icon: '≋',  label: 'air exch', color: 'air_exchange' },
    outdoor:      { icon: '☁',  label: 'outdoor',  color: 'outdoor' },
    ground:       { icon: '▓',  label: 'ground',   color: 'ground' },
  };

  function itemKind(item) {
    return item._type === 'room' ? 'room' : item.kind;
  }

  function connectivity(item) {
    if (item._type === 'room') return null;
    if (BOUNDARY_KINDS.includes(item.kind)) return null;
    const [a, b] = item.between ?? [];
    return a && b ? `${zoneLabel(a)} ↔ ${zoneLabel(b)}` : null;
  }

  function isBoundary(item) {
    return BOUNDARY_KINDS.includes(item.kind);
  }

  function signalIcons(item) {
    const hasInput = !!item.input_signal?.trim();
    const hasObs   = !!item.obs_signal?.trim();
    const hasSolar = !!item.solar_signal?.trim();
    return { hasInput, hasObs, hasSolar, any: hasInput || hasObs || hasSolar };
  }
</script>

<div class="house-panel">

  <!-- ── toolbar ───────────────────────────────────────────────────────────── -->
  <div class="toolbar">
    <div class="toolbar-row toolbar-row-name">
      <input
        class="house-name-input"
        type="text"
        value={house?.label ?? ''}
        oninput={(e) => patchHouse({ label: e.target.value })}
        placeholder="House name"
      />
      {#if ondelete}
        <button class="toolbar-delete" onclick={() => {
          if (confirm(`Delete "${house?.label || 'this house'}"? This cannot be undone.`)) ondelete();
        }} title="Delete house">Delete</button>
      {/if}
    </div>
    <div class="toolbar-row">
      <div class="add-menu-wrap" use:clickOutside>
        <button class="toolbar-btn add-menu-trigger" onclick={() => addMenuOpen = !addMenuOpen} title="Add element">
          <span class="tb-icon">＋</span>
          <span class="tb-text">Add</span>
          <span class="tb-caret">{addMenuOpen ? '▴' : '▾'}</span>
        </button>
        {#if addMenuOpen}
          <div class="add-menu-dropdown">
            {#each [
              { kind: 'room',         icon: '⬜', label: 'Room' },
              { kind: 'opaque',       icon: '▬',  label: 'Wall / roof / floor' },
              { kind: 'glazing',      icon: '◻',  label: 'Window / door' },
              { kind: 'air_exchange', icon: '≋',  label: 'Air exchange' },
              { kind: 'outdoor',      icon: '☁',  label: 'Outdoor zone' },
              { kind: 'ground',       icon: '▓',  label: 'Ground zone' },
            ] as btn}
              <button
                class="add-menu-item kind-btn-{btn.kind}"
                onclick={() => { btn.kind === 'room' ? addRoom() : addElement(btn.kind); addMenuOpen = false; }}
              >
                <span class="tb-icon">{btn.icon}</span>
                <span>{btn.label}</span>
              </button>
            {/each}
          </div>
        {/if}
      </div>
    </div>
    <div class="toolbar-row">
      {#if onsave}
        {#if saveError}<span class="toolbar-save-error">{saveError}</span>{/if}
        <button class="toolbar-save" class:dirty onclick={onsave} disabled={saveLoading}>
          {saveLoading ? 'Saving…' : dirty ? 'Save ●' : 'Save'}
        </button>
      {/if}
    </div>
  </div>


  <!-- ── grid header ────────────────────────────────────────────────────────── -->
  <div class="grid-header">
    <span></span>
    <span>label</span>
    <span>connectivity</span>
    <span class="col-signals"></span>
    <span class="col-role">role</span>
  </div>

  <!-- ── flat list ──────────────────────────────────────────────────────────── -->
  <div class="list">
    {#each flatItems as item (item.id)}
      {@const kind = itemKind(item)}
      {@const meta = KIND_META[kind]}
      {@const expanded = expandedId === item.id}
      {@const boundary = isBoundary(item)}
      {@const conn = connectivity(item)}
      {@const figures = keyFigures(item)}
      {@const displayLabel = item.label || `(${meta.label})`}

      {@const sigs = signalIcons(item)}

      <div class="row" class:expanded>

        <!-- ── row header (grid row) ── -->
        <div class="row-header" role="button" tabindex="0"
          onclick={() => toggleExpand(item.id)}
          onkeydown={(e) => e.key === 'Enter' && toggleExpand(item.id)}>
          <!-- row 1: icon | label | connectivity | signals | role -->
          <span class="kind-icon kind-{kind}" title={meta.label}>{meta.icon}</span>
          <span class="row-label" class:placeholder={!item.label}>{displayLabel}</span>
          <span class="row-conn">{conn ?? ''}</span>
          <span class="col-signals">
            {#if sigs.hasInput}<span class="sig-icon sig-input" title="Input signal: {item.input_signal}">⤵</span>{/if}
            {#if sigs.hasObs}<span class="sig-icon sig-obs" title="Observation signal: {item.obs_signal}">◉</span>{/if}
            {#if sigs.hasSolar}<span class="sig-icon sig-solar" title="Solar signal: {item.solar_signal}">☀</span>{/if}
          </span>
          <span class="col-role">
            {#if item._type === 'room' || item.kind === 'ground'}
              {@const role = item.role ?? 'mass'}
              <span class="role-badge role-{role}">{role}</span>
            {:else if item.kind === 'outdoor'}
              <span class="role-badge role-boundary">boundary</span>
            {/if}
          </span>
          <!-- row 2: chevron | figures -->
          <span class="row-chevron">{expanded ? '▲' : '▼'}</span>
          <span class="row-figures">{figures ?? ''}</span>
        </div>

        <!-- ── inline editor ── -->
        {#if expanded}
          <div class="row-editor">

            {#if kind === 'room'}
              {@const roomRole = item.role ?? 'mass'}
              <div class="field-row">
                <label class="field">
                  <span>label</span>
                  <input type="text" value={item.label ?? ''}
                    oninput={(e) => patchRoom(item.id, { label: e.target.value })}
                    placeholder="Room name" />
                </label>
                <label class="field">
                  <span>role</span>
                  <select value={roomRole}
                    onchange={(e) => patchRoom(item.id, { role: e.target.value })}>
                    <option value="mass">mass (solve T)</option>
                    <option value="boundary">boundary (T from signal)</option>
                    <option value="fixed">fixed (constant T)</option>
                  </select>
                </label>
                {#if roomRole === 'mass' || roomRole === 'boundary'}
                  <label class="field">
                    <span>a (m)</span>
                    <input type="number" value={item.a} min="0.1" step="0.5"
                      oninput={(e) => patchRoom(item.id, { a: parseFloat(e.target.value) || 0 })} />
                  </label>
                  <label class="field">
                    <span>b (m)</span>
                    <input type="number" value={item.b} min="0.1" step="0.5"
                      oninput={(e) => patchRoom(item.id, { b: parseFloat(e.target.value) || 0 })} />
                  </label>
                  <label class="field">
                    <span>c (m)</span>
                    <input type="number" value={item.c} min="0.1" step="0.1"
                      oninput={(e) => patchRoom(item.id, { c: parseFloat(e.target.value) || 0 })} />
                  </label>
                  <div class="field">
                    <span>volume</span>
                    <span class="computed-val">{((item.a ?? 0)*(item.b ?? 0)*(item.c ?? 0)).toFixed(1)} m³</span>
                  </div>
                {/if}
                {#if roomRole === 'mass'}
                  <label class="field">
                    <span>furniture factor</span>
                    <input type="number" value={item.furniture_factor ?? 2.5} min="1" step="0.5"
                      oninput={(e) => patchRoom(item.id, { furniture_factor: parseFloat(e.target.value) || 1 })} />
                  </label>
                {/if}
                {#if roomRole === 'fixed'}
                  <label class="field">
                    <span>T fixed (°C)</span>
                    <input type="number" value={item.T_fixed ?? 20} step="0.5"
                      oninput={(e) => patchRoom(item.id, { T_fixed: parseFloat(e.target.value) })} />
                  </label>
                {/if}
              </div>
              <div class="signals-section">
                <div class="signals-title">Signals</div>
                <div class="field-row">
                  {#if roomRole === 'mass'}
                    <SignalPicker
                      {signals}
                      label="⤵ input (heat source)"
                      value={item.input_signal ?? ''}
                      onpick={(v) => patchRoom(item.id, { input_signal: v || undefined })}
                    />
                  {/if}
                  {#if roomRole === 'mass' || roomRole === 'boundary'}
                    <SignalPicker
                      {signals}
                      label="◉ observation (T° sensor)"
                      value={item.obs_signal ?? ''}
                      onpick={(v) => patchRoom(item.id, { obs_signal: v || undefined })}
                    />
                  {/if}
                </div>
              </div>

            {:else if item.kind === 'opaque'}
              <div class="field-row">
                <label class="field">
                  <span>label</span>
                  <input type="text" value={item.label ?? ''}
                    oninput={(e) => patchElement(item.id, { label: e.target.value })}
                    placeholder="Wall name" />
                </label>
                <label class="field">
                  <span>from</span>
                  <select value={item.between?.[0]}
                    onchange={(e) => patchElement(item.id, { between: [e.target.value, item.between[1]] })}>
                    {#each zoneOptions as z}<option value={z.id}>{z.label}</option>{/each}
                  </select>
                </label>
                <label class="field">
                  <span>to</span>
                  <select value={item.between?.[1]}
                    onchange={(e) => patchElement(item.id, { between: [item.between[0], e.target.value] })}>
                    {#each zoneOptions as z}<option value={z.id}>{z.label}</option>{/each}
                  </select>
                </label>
                <label class="field">
                  <span>a (m)</span>
                  <input type="number" value={item.a} min="0.1" step="0.1"
                    oninput={(e) => patchElement(item.id, { a: parseFloat(e.target.value) || 0 })} />
                </label>
                <label class="field">
                  <span>b (m)</span>
                  <input type="number" value={item.b} min="0.1" step="0.1"
                    oninput={(e) => patchElement(item.id, { b: parseFloat(e.target.value) || 0 })} />
                </label>
                <div class="field">
                  <span>area</span>
                  <span class="computed-val">{((item.a ?? 0)*(item.b ?? 0)).toFixed(2)} m²</span>
                </div>
                <label class="field">
                  <span>orientation</span>
                  <select value={item.orientation ?? 'S'}
                    onchange={(e) => patchElement(item.id, { orientation: e.target.value })}>
                    {#each ORIENTATIONS as o}<option value={o}>{o}</option>{/each}
                  </select>
                </label>
                <label class="field">
                  <span>tilt (°)</span>
                  <input type="number" value={item.tilt ?? 90} min="0" max="90" step="5"
                    oninput={(e) => patchElement(item.id, { tilt: parseFloat(e.target.value) || 90 })} />
                </label>
                <label class="field" title="Solar absorptance α — dark brick ≈ 0.7, light render ≈ 0.3, white paint ≈ 0.15">
                  <span>solar α</span>
                  <input type="number" value={item.solar_absorptance ?? 0} min="0" max="1" step="0.05"
                    oninput={(e) => patchElement(item.id, { solar_absorptance: parseFloat(e.target.value) ?? 0 })} />
                </label>
                <label class="field" title="Approximate the wall as a pure resistor — no thermal mass, faster simulation">
                  <span>no mass</span>
                  <input type="checkbox" checked={item.no_mass ?? false}
                    onchange={(e) => patchElement(item.id, { no_mass: e.target.checked || undefined })} />
                </label>
              </div>
              <div class="layers-section">
                <div class="layers-title">
                  Layers (interior → exterior)
                  <span class="layers-total-r">R total = {opaqueTotalR(item).toFixed(3)} m²K/W</span>
                </div>
                {#each item.layers ?? [] as layer, i}
                  <div class="layer-row">
                    <span class="layer-num">{i + 1}</span>
                    <label class="field">
                      <span>material</span>
                      <select value={layer.material}
                        onchange={(e) => patchLayer(item.id, i, { material: e.target.value })}>
                        {#each Object.entries(materials) as [id, m]}
                          <option value={id}>{m.name ?? id}</option>
                        {/each}
                      </select>
                    </label>
                    <label class="field">
                      <span>thickness (m)</span>
                      <input type="number" value={layer.thickness} min="0.001" step="0.01"
                        oninput={(e) => patchLayer(item.id, i, { thickness: parseFloat(e.target.value) || 0.01 })} />
                    </label>
                    <div class="field">
                      <span>R (m²K/W)</span>
                      <span class="computed-val">
                        {(() => { const r = opaqueLayerR(layer); return r != null ? r.toFixed(3) : '—'; })()}
                      </span>
                    </div>
                    <button class="icon-btn del-btn" onclick={() => deleteLayer(item.id, i)} title="Remove">×</button>
                  </div>
                {/each}
                <button class="add-layer-btn" onclick={() => addLayer(item.id)}>+ Layer</button>
              </div>

            {:else if item.kind === 'glazing'}
              <div class="field-row">
                <label class="field">
                  <span>label</span>
                  <input type="text" value={item.label ?? ''}
                    oninput={(e) => patchElement(item.id, { label: e.target.value })}
                    placeholder="Window name" />
                </label>
                <label class="field">
                  <span>from</span>
                  <select value={item.between?.[0]}
                    onchange={(e) => patchElement(item.id, { between: [e.target.value, item.between[1]] })}>
                    {#each zoneOptions as z}<option value={z.id}>{z.label}</option>{/each}
                  </select>
                </label>
                <label class="field">
                  <span>to</span>
                  <select value={item.between?.[1]}
                    onchange={(e) => patchElement(item.id, { between: [item.between[0], e.target.value] })}>
                    {#each zoneOptions as z}<option value={z.id}>{z.label}</option>{/each}
                  </select>
                </label>
                <label class="field">
                  <span>a (m)</span>
                  <input type="number" value={item.a} min="0.1" step="0.1"
                    oninput={(e) => patchElement(item.id, { a: parseFloat(e.target.value) || 0 })} />
                </label>
                <label class="field">
                  <span>b (m)</span>
                  <input type="number" value={item.b} min="0.1" step="0.1"
                    oninput={(e) => patchElement(item.id, { b: parseFloat(e.target.value) || 0 })} />
                </label>
                <div class="field">
                  <span>area</span>
                  <span class="computed-val">{((item.a ?? 0)*(item.b ?? 0)).toFixed(2)} m²</span>
                </div>
                <label class="field">
                  <span>orientation</span>
                  <select value={item.orientation ?? 'S'}
                    onchange={(e) => patchElement(item.id, { orientation: e.target.value })}>
                    {#each ORIENTATIONS as o}<option value={o}>{o}</option>{/each}
                  </select>
                </label>
                <label class="field">
                  <span>U (W/m²K)</span>
                  <input type="number" value={item.U} min="0.1" step="0.1"
                    oninput={(e) => patchElement(item.id, { U: parseFloat(e.target.value) || 0 })} />
                </label>
                <label class="field">
                  <span>SHGC</span>
                  <input type="number" value={item.SHGC} min="0" max="1" step="0.01"
                    oninput={(e) => patchElement(item.id, { SHGC: parseFloat(e.target.value) || 0 })} />
                </label>
              </div>

            {:else if item.kind === 'air_exchange'}
              <div class="field-row">
                <label class="field">
                  <span>label</span>
                  <input type="text" value={item.label ?? ''}
                    oninput={(e) => patchElement(item.id, { label: e.target.value })}
                    placeholder="Air exchange name" />
                </label>
                <label class="field">
                  <span>from</span>
                  <select value={item.between?.[0]}
                    onchange={(e) => patchElement(item.id, { between: [e.target.value, item.between[1]] })}>
                    {#each zoneOptions as z}<option value={z.id}>{z.label}</option>{/each}
                  </select>
                </label>
                <label class="field">
                  <span>to</span>
                  <select value={item.between?.[1]}
                    onchange={(e) => patchElement(item.id, { between: [item.between[0], e.target.value] })}>
                    {#each zoneOptions as z}<option value={z.id}>{z.label}</option>{/each}
                  </select>
                </label>
                <label class="field">
                  <span>ACH (h⁻¹)</span>
                  <input type="number" value={item.ach} min="0.01" step="0.1"
                    oninput={(e) => patchElement(item.id, { ach: parseFloat(e.target.value) || 0 })} />
                </label>
              </div>

            {:else if item.kind === 'outdoor'}
              <div class="field-row">
                <label class="field">
                  <span>label</span>
                  <input type="text" value={item.label ?? ''}
                    oninput={(e) => patchElement(item.id, { label: e.target.value })}
                    placeholder="Outdoor zone name" />
                </label>
                <label class="field">
                  <span>city</span>
                  <input type="text" value={item.location?.label ?? ''}
                    oninput={(e) => patchElement(item.id, { location: { ...item.location, label: e.target.value } })} />
                </label>
                <label class="field">
                  <span>lat</span>
                  <input type="number" value={item.location?.lat ?? ''} step="0.01"
                    oninput={(e) => patchElement(item.id, { location: { ...item.location, lat: parseFloat(e.target.value) } })} />
                </label>
                <label class="field">
                  <span>lon</span>
                  <input type="number" value={item.location?.lon ?? ''} step="0.01"
                    oninput={(e) => patchElement(item.id, { location: { ...item.location, lon: parseFloat(e.target.value) } })} />
                </label>
              </div>
              <div class="signals-section">
                <div class="signals-title">Signals</div>
                <div class="field-row">
                  <SignalPicker
                    {signals}
                    label="◉ temperature"
                    value={item.obs_signal ?? ''}
                    onpick={(v) => patchElement(item.id, { obs_signal: v || undefined })}
                  />
                  <SignalPicker
                    {signals}
                    label="☀ solar radiation (W/m²)"
                    value={item.solar_signal ?? ''}
                    onpick={(v) => patchElement(item.id, { solar_signal: v || undefined })}
                  />
                </div>
              </div>

            {:else if item.kind === 'ground'}
              <div class="field-row">
                <label class="field">
                  <span>label</span>
                  <input type="text" value={item.label ?? ''}
                    oninput={(e) => patchElement(item.id, { label: e.target.value })}
                    placeholder="Ground zone name" />
                </label>
                <label class="field">
                  <span>T fixed (°C)</span>
                  <input type="number" value={item.T_fixed ?? 10} step="0.5"
                    oninput={(e) => patchElement(item.id, { T_fixed: parseFloat(e.target.value) })} />
                </label>
              </div>
            {/if}

            <div class="editor-footer">
              <button class="delete-btn"
                onclick={() => kind === 'room' ? deleteRoom(item.id) : deleteElement(item.id)}>
                Delete
              </button>
            </div>

          </div>
        {/if}
      </div>
    {/each}
  </div>

</div>

<style>
  .house-panel {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
  }

  /* ── toolbar ── */
  .toolbar {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 7px 14px;
    border-bottom: 1px solid #1e293b;
    flex-shrink: 0;
  }

  .toolbar-row {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }

  .toolbar-row-name {
    gap: 8px;
  }

  .house-name-input {
    flex: 1;
    background: transparent;
    border: 1px solid transparent;
    color: #e2e8f0;
    font-size: 13px;
    font-weight: 600;
    font-family: inherit;
    padding: 3px 6px;
    border-radius: 4px;
    min-width: 0;
  }
  .house-name-input:hover { border-color: #334155; }
  .house-name-input:focus { outline: none; border-color: #6366f1; background: #0f172a; }
  .house-name-input::placeholder { color: #475569; font-weight: 400; font-style: italic; }

  .toolbar-delete {
    padding: 3px 10px;
    border-radius: 4px;
    border: 1px solid #334155;
    background: transparent;
    color: #64748b;
    font-size: 11px;
    cursor: pointer;
    flex-shrink: 0;
  }
  .toolbar-delete:hover { color: #ef4444; border-color: #ef4444; background: transparent; }

  .toolbar-btn {
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 4px 10px;
    border-radius: 5px;
    border: 1px solid #334155;
    background: #1e293b;
    color: #94a3b8;
    font-size: 12px;
    cursor: pointer;
    transition: background 0.1s, color 0.1s;
  }
  .toolbar-btn:hover { background: #273548; color: #e2e8f0; }

  .tb-icon { font-size: 14px; line-height: 1; }
  .tb-text { font-size: 11px; }
  .tb-caret { font-size: 9px; margin-left: 2px; }

  .add-menu-wrap {
    position: relative;
  }

  .add-menu-dropdown {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    z-index: 100;
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 4px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 170px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.4);
  }

  .add-menu-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 5px 10px;
    border-radius: 4px;
    border: none;
    background: transparent;
    color: #94a3b8;
    font-size: 12px;
    cursor: pointer;
    text-align: left;
    transition: background 0.1s, color 0.1s;
  }
  .add-menu-item:hover                        { background: #273548; color: #e2e8f0; }
  .kind-btn-opaque.add-menu-item:hover        { background: #1e3a5f; color: #93c5fd; }
  .kind-btn-glazing.add-menu-item:hover       { background: #14532d; color: #86efac; }
  .kind-btn-air_exchange.add-menu-item:hover  { background: #451a03; color: #fcd34d; }
  .kind-btn-outdoor.add-menu-item:hover       { background: #0c2340; color: #7dd3fc; }
  .kind-btn-ground.add-menu-item:hover        { background: #1a1a2e; color: #a78bfa; }

.toolbar-save {
    padding: 4px 12px;
    border-radius: 5px;
    border: 1px solid #334155;
    background: #1e293b;
    color: #64748b;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
  }
  .toolbar-save:hover { background: #273548; color: #94a3b8; }
  .toolbar-save.dirty { border-color: #f59e0b; color: #fcd34d; background: #1c1a07; }
  .toolbar-save.dirty:hover { background: #2a2506; }
  .toolbar-save:disabled { opacity: 0.5; cursor: default; }

  .toolbar-save-error {
    font-size: 10px;
    color: #f87171;
  }

  /* ── grid columns: icon | label | connectivity | signals | role ── */
  .grid-header,
  .row-header {
    display: grid;
    grid-template-columns: 26px 1fr 1.4fr 36px 70px;
    align-items: center;
    gap: 0;
  }

  /* row-header: 2 rows
     row 1 — icon | label | connectivity | signals | role
     row 2 — chevron | figures (spans cols 2–5)            */
  .row-header {
    grid-template-rows: auto auto;
  }
  .row-header .kind-icon   { grid-row: 1; grid-column: 1; }
  .row-header .row-label   { grid-row: 1; grid-column: 2; }
  .row-header .row-conn    { grid-row: 1; grid-column: 3; }
  .row-header .col-signals { grid-row: 1; grid-column: 4; }
  .row-header .col-role    { grid-row: 1; grid-column: 5; }
  .row-header .row-chevron { grid-row: 2; grid-column: 1; }
  .row-header .row-figures { grid-row: 2; grid-column: 2 / 6; }

  .grid-header {
    padding: 4px 14px;
    border-bottom: 1px solid #1e293b;
    flex-shrink: 0;
  }
  .grid-header > span {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: #475569;
    padding: 0 6px;
  }

  /* ── flat list ── */
  .list {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 6px 14px;
  }

  .row {
    background: #1e293b;
    border: 1px solid #263347;
    border-radius: 5px;
    overflow: hidden;
  }
  .row.expanded { border-color: #6366f1; }

  .row-header {
    padding: 5px 6px;
    cursor: pointer;
    user-select: none;
  }
  .row-header:hover { background: #243044; }

  .kind-icon {
    font-size: 14px;
    text-align: center;
    flex-shrink: 0;
    padding: 0 2px;
  }

  .kind-room         { color: #a5b4fc; }
  .kind-opaque       { color: #93c5fd; }
  .kind-glazing      { color: #86efac; }
  .kind-air_exchange { color: #fcd34d; }
  .kind-outdoor      { color: #7dd3fc; }
  .kind-ground       { color: #a78bfa; }

  .row-label {
    font-size: 12px;
    font-weight: 600;
    color: #e2e8f0;
    padding: 0 8px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .row-label.placeholder {
    color: #475569;
    font-weight: 400;
    font-style: italic;
  }

  .row-conn {
    font-size: 10px;
    color: #64748b;
    padding: 0 8px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .row-figures {
    font-size: 10px;
    color: #94a3b8;
    font-family: monospace;
    padding: 0 8px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .col-role {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0 4px;
  }

  .role-badge {
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 2px 5px;
    border-radius: 3px;
    white-space: nowrap;
  }
  .role-mass     { background: #1e3a5f; color: #93c5fd; }
  .role-boundary { background: #14532d; color: #86efac; }
  .role-fixed    { background: #3b0764; color: #d8b4fe; }

  .row-chevron {
    font-size: 10px;
    color: #475569;
    text-align: right;
    padding-right: 4px;
  }

  .row-editor {
    border-top: 1px solid #334155;
    padding: 12px;
    background: #0f172a;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .editor-footer {
    border-top: 1px solid #1e293b;
    padding-top: 8px;
    margin-top: 2px;
  }

  .delete-btn {
    background: transparent;
    color: #64748b;
    border: 1px solid #334155;
    border-radius: 4px;
    padding: 4px 12px;
    font-size: 11px;
    cursor: pointer;
  }
  .delete-btn:hover { color: #ef4444; border-color: #ef4444; }

  /* ── layers ── */
  .layers-section {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .layers-title {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #94a3b8;
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }
  .layers-total-r {
    font-size: 11px;
    font-family: monospace;
    color: #cbd5e1;
    text-transform: none;
    letter-spacing: 0;
  }
  .layer-row {
    display: flex;
    align-items: flex-end;
    gap: 8px;
  }
  .layer-num {
    font-size: 10px;
    color: #64748b;
    font-family: monospace;
    padding-bottom: 6px;
    flex-shrink: 0;
  }
  .add-layer-btn {
    align-self: flex-start;
    font-size: 11px;
    padding: 3px 8px;
  }

  /* ── shared form helpers ── */
  .field-row {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 80px;
  }
  .field > span {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #94a3b8;
    white-space: nowrap;
  }

  input, select {
    background: #0f172a;
    color: #e2e8f0;
    border: 1px solid #334155;
    border-radius: 4px;
    padding: 4px 6px;
    font-size: 12px;
    font-family: monospace;
    width: 100%;
    box-sizing: border-box;
  }
  input:focus, select:focus { outline: none; border-color: #6366f1; }

  .computed-val {
    font-size: 12px;
    font-family: monospace;
    color: #94a3b8;
    padding: 4px 6px;
    background: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 4px;
  }

  .icon-btn {
    background: transparent;
    border: none;
    color: #94a3b8;
    font-size: 14px;
    line-height: 1;
    cursor: pointer;
    padding: 2px 4px;
    border-radius: 3px;
    flex-shrink: 0;
  }
  .icon-btn:hover  { background: #334155; color: #f1f5f9; }
  .del-btn:hover   { color: #ef4444; }

  /* ── signal icons (collapsed row) ── */
  .col-signals {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 3px;
    padding: 0 2px;
  }

  .sig-icon {
    font-size: 11px;
    line-height: 1;
    cursor: default;
  }
  .sig-input { color: #fbbf24; }
  .sig-obs   { color: #818cf8; }
  .sig-solar { color: #fb923c; }

  /* ── signals section (expanded editor) ── */
  .signals-section {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding-top: 6px;
    border-top: 1px solid #1e293b;
  }

  .signals-title {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #94a3b8;
  }

  .field-wide {
    min-width: 240px;
    flex: 1;
  }

  .sig-label {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .sig-label-input { color: #fbbf24; }
  .sig-label-obs   { color: #818cf8; }
  .sig-label-solar { color: #fb923c; }
</style>
