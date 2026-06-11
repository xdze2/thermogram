<script>
  /**
   * Props:
   *   materials:        { [id]: { lambda, rho, cp, name, category, source, notes } }  — custom materials
   *   customConstants:  { [id]: { value } }  — project overrides for constants
   *   onchange:         (newMaterials) => void
   *   onconstants:      (newConstants) => void
   */
  let { materials = {}, customConstants = {}, onchange, onconstants } = $props();

  // ── built-in materials ────────────────────────────────────────────────────
  const BUILTIN_MATERIALS = {
    brick_full:     { lambda: 0.8,   rho: 1800, cp: 840,  name: 'Brique pleine',      category: 'masonry',    source: 'EN ISO 10456:2007 Table 2' },
    brick_hollow:   { lambda: 0.45,  rho: 1200, cp: 840,  name: 'Brique creuse',      category: 'masonry',    source: 'RT2012 Th-BCE' },
    stone_calcaire: { lambda: 1.7,   rho: 2200, cp: 900,  name: 'Calcaire',           category: 'masonry',    source: 'EN ISO 10456:2007 Table 2' },
    stone_rubble:   { lambda: 1.3,   rho: 2000, cp: 900,  name: 'Moellon',            category: 'masonry',    source: 'RT2012 Th-BCE' },
    concrete_heavy: { lambda: 1.75,  rho: 2300, cp: 840,  name: 'Béton lourd',        category: 'masonry',    source: 'EN ISO 10456:2007 Table 2' },
    concrete_slab:  { lambda: 1.65,  rho: 2200, cp: 840,  name: 'Dalle béton',        category: 'masonry',    source: 'RT2012 Th-BCE' },
    glass_wool:     { lambda: 0.035, rho: 15,   cp: 840,  name: 'Laine de verre',     category: 'insulation', source: 'EN ISO 10456:2007 Table 2' },
    rock_wool:      { lambda: 0.038, rho: 30,   cp: 840,  name: 'Laine de roche',     category: 'insulation', source: 'EN ISO 10456:2007 Table 2' },
    cellulose:      { lambda: 0.040, rho: 50,   cp: 1900, name: 'Ouate de cellulose', category: 'insulation', source: 'RT2012 Th-BCE' },
    plaster:        { lambda: 0.57,  rho: 1200, cp: 1000, name: 'Plâtre',             category: 'finish',     source: 'EN ISO 10456:2007 Table 2' },
    lime_plaster:   { lambda: 0.87,  rho: 1600, cp: 1000, name: 'Enduit chaux',       category: 'finish',     source: 'RT2012 Th-BCE' },
    wood_frame:     { lambda: 0.13,  rho: 530,  cp: 1600, name: 'Bois (structure)',   category: 'wood',       source: 'EN ISO 10456:2007 Table 2' },
    wood_floor:     { lambda: 0.16,  rho: 700,  cp: 1600, name: 'Parquet',            category: 'wood',       source: 'RT2012 Th-BCE' },
    tile_clay:      { lambda: 1.0,   rho: 1900, cp: 840,  name: 'Tuile terre cuite',  category: 'finish',     source: 'RT2012 Th-BCE' },
  };

  const CATEGORIES = ['masonry', 'insulation', 'finish', 'wood', 'other'];

  const allMaterials = $derived({ ...BUILTIN_MATERIALS, ...(materials ?? {}) });

  const byCategory = $derived(() => {
    const groups = {};
    for (const [id, m] of Object.entries(allMaterials)) {
      const cat = m.category ?? 'other';
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push({ id, ...m, builtin: id in BUILTIN_MATERIALS });
    }
    return groups;
  });

  // ── built-in constants ────────────────────────────────────────────────────
  const BUILTIN_CONSTANTS = {
    h_i:          { value: 7.7,    unit: 'W/m²·K', name: 'h_i — conv. int. (flux horiz.)',   source: 'ISO 6946:2017 §6.7.1' },
    h_i_upward:   { value: 10.0,   unit: 'W/m²·K', name: 'h_i — conv. int. (flux montant)',  source: 'ISO 6946:2017 §6.7.1' },
    h_i_downward: { value: 5.9,    unit: 'W/m²·K', name: 'h_i — conv. int. (flux descend.)', source: 'ISO 6946:2017 §6.7.1' },
    h_e:          { value: 25.0,   unit: 'W/m²·K', name: 'h_e — conv. ext. (exposé au vent)',source: 'ISO 6946:2017 §6.9.2' },
    h_e_sheltered:{ value: 12.0,   unit: 'W/m²·K', name: 'h_e — conv. ext. (abrité)',        source: 'ISO 6946:2017 §6.9.2' },
    rho_air:      { value: 1.204,  unit: 'kg/m³',  name: 'ρ air — masse volumique',           source: 'air sec à 20°C, 101325 Pa' },
    cp_air:       { value: 1006,   unit: 'J/kg·K', name: 'cp air — chaleur spécifique',       source: 'air sec à 20°C' },
  };

  // effective value: custom override if present, else builtin
  function constValue(id) {
    return customConstants?.[id]?.value ?? BUILTIN_CONSTANTS[id]?.value;
  }

  // ── active section in left nav ────────────────────────────────────────────
  let activeSection = $state('materials');  // 'materials' | 'constants'

  // ── selected item ─────────────────────────────────────────────────────────
  let selectedId     = $state(null);
  let selectedKind   = $state(null);  // 'material' | 'constant'

  const selectedMat  = $derived(
    selectedKind === 'material' && selectedId ? { id: selectedId, ...allMaterials[selectedId] } : null
  );
  const selectedConst = $derived(
    selectedKind === 'constant' && selectedId ? { id: selectedId, ...BUILTIN_CONSTANTS[selectedId] } : null
  );
  const selectedBuiltin = $derived(
    selectedKind === 'material' ? (selectedId in BUILTIN_MATERIALS) : true
  );
  const constOverridden = $derived(
    selectedKind === 'constant' && selectedId ? (selectedId in (customConstants ?? {})) : false
  );

  function selectMat(id) {
    if (selectedId === id && selectedKind === 'material') { selectedId = null; selectedKind = null; return; }
    selectedId   = id;
    selectedKind = 'material';
    showAddForm  = false;
    if (!(id in BUILTIN_MATERIALS)) {
      editName     = allMaterials[id]?.name ?? '';
      editLambda   = allMaterials[id]?.lambda ?? 0.1;
      editRho      = allMaterials[id]?.rho ?? 1000;
      editCp       = allMaterials[id]?.cp ?? 840;
      editCategory = allMaterials[id]?.category ?? 'other';
      editSource   = allMaterials[id]?.source ?? '';
      editNotes    = allMaterials[id]?.notes ?? '';
    }
  }

  function selectConst(id) {
    if (selectedId === id && selectedKind === 'constant') { selectedId = null; selectedKind = null; return; }
    selectedId    = id;
    selectedKind  = 'constant';
    showAddForm   = false;
    editConstVal  = constValue(id);
  }

  // ── add / edit custom material ────────────────────────────────────────────
  let showAddForm  = $state(false);
  let addId        = $state('');
  let addName      = $state('');
  let addLambda    = $state(0.1);
  let addRho       = $state(1000);
  let addCp        = $state(840);
  let addCategory  = $state('other');
  let addSource    = $state('');
  let addNotes     = $state('');
  let addError     = $state('');

  function addMaterial() {
    const id = addId.trim();
    if (!id) { addError = 'ID required'; return; }
    if (id in allMaterials) { addError = 'ID already exists'; return; }
    const m = { name: addName.trim() || id, lambda: addLambda, rho: addRho, cp: addCp, category: addCategory };
    if (addSource.trim()) m.source = addSource.trim();
    if (addNotes.trim())  m.notes  = addNotes.trim();
    onchange({ ...(materials ?? {}), [id]: m });
    addId = ''; addName = ''; addLambda = 0.1; addRho = 1000; addCp = 840;
    addCategory = 'other'; addSource = ''; addNotes = ''; addError = '';
    showAddForm = false;
    selectedId = id; selectedKind = 'material';
  }

  // inline edit for custom material
  let editName     = $state('');
  let editLambda   = $state(0.1);
  let editRho      = $state(1000);
  let editCp       = $state(840);
  let editCategory = $state('other');
  let editSource   = $state('');
  let editNotes    = $state('');

  function saveMaterialEdit() {
    if (!selectedId || selectedBuiltin) return;
    const m = { name: editName.trim() || selectedId, lambda: editLambda, rho: editRho, cp: editCp, category: editCategory };
    if (editSource.trim()) m.source = editSource.trim();
    if (editNotes.trim())  m.notes  = editNotes.trim();
    onchange({ ...(materials ?? {}), [selectedId]: m });
  }

  function deleteMaterial(id) {
    if (id in BUILTIN_MATERIALS) return;
    const m = { ...(materials ?? {}) };
    delete m[id];
    onchange(m);
    if (selectedId === id) { selectedId = null; selectedKind = null; }
  }

  // ── constant override ─────────────────────────────────────────────────────
  let editConstVal = $state(0);

  function saveConstOverride() {
    if (!selectedId) return;
    onconstants({ ...(customConstants ?? {}), [selectedId]: { value: editConstVal } });
  }

  function resetConst() {
    if (!selectedId) return;
    const c = { ...(customConstants ?? {}) };
    delete c[selectedId];
    onconstants(c);
    editConstVal = BUILTIN_CONSTANTS[selectedId]?.value ?? 0;
  }

  // ── helpers ───────────────────────────────────────────────────────────────
  function rVal(lambda) { return lambda > 0 ? (0.1 / lambda).toFixed(3) : '—'; }
</script>

<div class="mat-panel">

  <!-- ── left sidebar ───────────────────────────────────────────────────────── -->
  <aside class="mat-list">

    <!-- Materials section -->
    <div class="section-header">
      <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
      <span
        class="section-title"
        class:active={activeSection === 'materials'}
        onclick={() => activeSection = 'materials'}
      >Materials</span>
      <button class="add-btn" onclick={() => { showAddForm = !showAddForm; selectedId = null; activeSection = 'materials'; }}>+ Custom</button>
    </div>

    {#if activeSection === 'materials'}
      {#each CATEGORIES as cat}
        {#if byCategory()[cat]?.length}
          <div class="cat-label">{cat}</div>
          {#each byCategory()[cat] as m}
            <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
            <div
              class="mat-row"
              class:selected={m.id === selectedId && selectedKind === 'material'}
              onclick={() => selectMat(m.id)}
            >
              <span class="mat-name">{m.name ?? m.id}</span>
              <span class="mat-secondary">λ {m.lambda}</span>
              {#if !m.builtin}
                <button class="icon-btn del-btn" onclick={(e) => { e.stopPropagation(); deleteMaterial(m.id); }} title="Delete">×</button>
              {/if}
            </div>
          {/each}
        {/if}
      {/each}
    {/if}

    <div class="list-divider"></div>

    <!-- Constants section -->
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div
      class="section-header clickable"
      onclick={() => activeSection = 'constants'}
    >
      <span class="section-title" class:active={activeSection === 'constants'}>Constants</span>
    </div>

    {#if activeSection === 'constants'}
      {#each Object.entries(BUILTIN_CONSTANTS) as [id, c]}
        <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
        <div
          class="mat-row"
          class:selected={id === selectedId && selectedKind === 'constant'}
          onclick={() => selectConst(id)}
        >
          <span class="mat-name">{id}</span>
          <span class="mat-secondary" class:overridden={id in (customConstants ?? {})}>{constValue(id)} {c.unit}</span>
        </div>
      {/each}
    {/if}

  </aside>

  <!-- ── right: detail pane ─────────────────────────────────────────────────── -->
  <div class="mat-detail">

    {#if showAddForm}
      <div class="detail-card">
        <div class="detail-title">New custom material</div>
        <div class="field-row">
          <label class="field">
            <span>id</span>
            <input type="text" bind:value={addId} placeholder="my_material" />
          </label>
          <label class="field wide">
            <span>name</span>
            <input type="text" bind:value={addName} placeholder="My material" />
          </label>
          <label class="field">
            <span>category</span>
            <select bind:value={addCategory}>
              {#each CATEGORIES as c}<option value={c}>{c}</option>{/each}
            </select>
          </label>
        </div>
        <div class="field-row">
          <label class="field">
            <span>λ (W/m·K)</span>
            <input type="number" bind:value={addLambda} min="0.001" step="0.005" />
          </label>
          <label class="field">
            <span>ρ (kg/m³)</span>
            <input type="number" bind:value={addRho} min="1" step="50" />
          </label>
          <label class="field">
            <span>cp (J/kg·K)</span>
            <input type="number" bind:value={addCp} min="1" step="10" />
          </label>
        </div>
        <label class="field wide-full">
          <span>source</span>
          <input type="text" bind:value={addSource} placeholder="e.g. EN ISO 10456:2007 Table 2" />
        </label>
        <label class="field wide-full">
          <span>notes</span>
          <input type="text" bind:value={addNotes} placeholder="Optional comment" />
        </label>
        {#if addError}<div class="field-error">{addError}</div>{/if}
        <div class="form-actions">
          <button onclick={() => { showAddForm = false; addError = ''; }}>Cancel</button>
          <button class="primary" onclick={addMaterial}>Add</button>
        </div>
      </div>

    {:else if selectedMat}
      <div class="detail-card">
        <div class="detail-header">
          <span class="detail-id">{selectedMat.id}</span>
          {#if selectedBuiltin}
            <span class="badge-builtin">built-in</span>
          {:else}
            <span class="badge-custom">custom</span>
          {/if}
        </div>

        {#if selectedBuiltin}
          <div class="props-grid">
            <span class="prop-key">name</span>       <span class="prop-val">{selectedMat.name}</span>
            <span class="prop-key">category</span>   <span class="prop-val">{selectedMat.category ?? '—'}</span>
            <span class="prop-key">λ (W/m·K)</span>  <span class="prop-val">{selectedMat.lambda}</span>
            <span class="prop-key">ρ (kg/m³)</span>  <span class="prop-val">{selectedMat.rho}</span>
            <span class="prop-key">cp (J/kg·K)</span><span class="prop-val">{selectedMat.cp}</span>
            <span class="prop-key">R (10 cm)</span>   <span class="prop-val">{rVal(selectedMat.lambda)} m²·K/W</span>
            {#if selectedMat.source}
              <span class="prop-key">source</span>   <span class="prop-val prop-source">{selectedMat.source}</span>
            {/if}
          </div>

        {:else}
          <div class="field-row">
            <label class="field wide">
              <span>name</span>
              <input type="text" bind:value={editName} />
            </label>
            <label class="field">
              <span>category</span>
              <select bind:value={editCategory}>
                {#each CATEGORIES as c}<option value={c}>{c}</option>{/each}
              </select>
            </label>
          </div>
          <div class="field-row">
            <label class="field">
              <span>λ (W/m·K)</span>
              <input type="number" bind:value={editLambda} min="0.001" step="0.005" />
            </label>
            <label class="field">
              <span>ρ (kg/m³)</span>
              <input type="number" bind:value={editRho} min="1" step="50" />
            </label>
            <label class="field">
              <span>cp (J/kg·K)</span>
              <input type="number" bind:value={editCp} min="1" step="10" />
            </label>
          </div>
          <div class="computed-row">
            <span class="prop-key">R (10 cm ref)</span>
            <span class="prop-val">{rVal(editLambda)} m²·K/W</span>
          </div>
          <label class="field wide-full">
            <span>source</span>
            <input type="text" bind:value={editSource} placeholder="e.g. EN ISO 10456:2007 Table 2" />
          </label>
          <label class="field wide-full">
            <span>notes</span>
            <input type="text" bind:value={editNotes} />
          </label>
          <button class="primary save-btn" onclick={saveMaterialEdit}>Save</button>
        {/if}
      </div>

    {:else if selectedConst}
      <div class="detail-card">
        <div class="detail-header">
          <span class="detail-id">{selectedConst.id}</span>
          {#if constOverridden}
            <span class="badge-override">overridden</span>
          {:else}
            <span class="badge-builtin">default</span>
          {/if}
        </div>

        <div class="props-grid">
          <span class="prop-key">name</span>   <span class="prop-val">{selectedConst.name}</span>
          <span class="prop-key">default</span><span class="prop-val">{selectedConst.value} {selectedConst.unit}</span>
          {#if constOverridden}
            <span class="prop-key">project</span><span class="prop-val prop-override">{constValue(selectedConst.id)} {selectedConst.unit}</span>
          {/if}
          <span class="prop-key">source</span> <span class="prop-val prop-source">{selectedConst.source}</span>
        </div>

        <div class="const-edit-row">
          <label class="field">
            <span>project override ({selectedConst.unit})</span>
            <input type="number" bind:value={editConstVal} step="0.1" />
          </label>
          <div class="const-actions">
            <button class="primary save-btn" onclick={saveConstOverride}>Override</button>
            {#if constOverridden}
              <button class="reset-btn" onclick={resetConst}>Reset to default</button>
            {/if}
          </div>
        </div>
      </div>

    {:else}
      <div class="empty-hint">Select a material or constant to see its properties</div>
    {/if}

  </div>
</div>

<style>
  .mat-panel {
    display: flex;
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }

  /* ── sidebar ── */
  .mat-list {
    width: 240px;
    flex-shrink: 0;
    background: #1e293b;
    border-right: 1px solid #334155;
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    overflow-x: hidden;
  }

  .section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 14px 8px;
    flex-shrink: 0;
  }
  .section-header.clickable { cursor: pointer; }
  .section-header.clickable:hover { background: #243447; }

  .section-title {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #475569;
    transition: color 0.1s;
  }
  .section-title.active { color: #94a3b8; }

  .list-divider {
    height: 1px;
    background: #334155;
    margin: 6px 0;
    flex-shrink: 0;
  }

  .add-btn {
    font-size: 11px;
    padding: 3px 8px;
    background: #312e81;
    color: #a5b4fc;
    border: 1px solid #6366f1;
    border-radius: 4px;
    cursor: pointer;
  }
  .add-btn:hover { background: #3730a3; }

  .cat-label {
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #334155;
    padding: 8px 14px 3px;
  }

  .mat-row {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 14px;
    cursor: pointer;
    border-left: 3px solid transparent;
    transition: background 0.1s;
  }
  .mat-row:hover    { background: #243447; }
  .mat-row.selected { background: #243447; border-left-color: #6366f1; }

  .mat-name {
    flex: 1;
    font-size: 12px;
    color: #e2e8f0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .mat-secondary {
    font-size: 11px;
    font-family: monospace;
    color: #475569;
    flex-shrink: 0;
  }
  .mat-secondary.overridden { color: #f59e0b; }

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
  .icon-btn:hover { background: #334155; color: #f1f5f9; }
  .del-btn:hover  { color: #ef4444; }

  /* ── detail pane ── */
  .mat-detail {
    flex: 1;
    overflow-y: auto;
    padding: 20px 24px;
    display: flex;
    flex-direction: column;
  }

  .empty-hint {
    color: #94a3b8;
    font-size: 13px;
    margin: auto;
    align-self: center;
  }

  .detail-card {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 18px 20px;
    display: flex;
    flex-direction: column;
    gap: 14px;
    max-width: 500px;
  }

  .detail-header {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .detail-title {
    font-size: 13px;
    font-weight: 600;
    color: #f1f5f9;
  }

  .detail-id {
    font-size: 14px;
    font-weight: 700;
    font-family: monospace;
    color: #f1f5f9;
  }

  .badge-builtin {
    font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
    padding: 2px 6px; border-radius: 3px; background: #1e3a5f; color: #93c5fd;
  }
  .badge-custom {
    font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
    padding: 2px 6px; border-radius: 3px; background: #14532d; color: #86efac;
  }
  .badge-override {
    font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
    padding: 2px 6px; border-radius: 3px; background: #451a03; color: #fcd34d;
  }

  .props-grid {
    display: grid;
    grid-template-columns: 90px 1fr;
    gap: 6px 12px;
    align-items: baseline;
  }

  .prop-key {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #94a3b8;
  }

  .prop-val {
    font-size: 13px;
    font-family: monospace;
    color: #e2e8f0;
  }

  .prop-source {
    font-size: 11px;
    font-family: monospace;
    color: #475569;
    font-style: italic;
  }

  .prop-override { color: #f59e0b; }

  .computed-row {
    display: flex;
    align-items: baseline;
    gap: 12px;
  }

  .const-edit-row {
    display: flex;
    align-items: flex-end;
    gap: 12px;
    flex-wrap: wrap;
  }

  .const-actions {
    display: flex;
    gap: 8px;
    align-items: center;
    padding-bottom: 1px;
  }

  .reset-btn {
    font-size: 11px;
    padding: 4px 10px;
    background: none;
    color: #94a3b8;
    border: 1px solid #334155;
    border-radius: 4px;
    cursor: pointer;
  }
  .reset-btn:hover { background: #334155; color: #f1f5f9; }

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
  .field.wide      { min-width: 160px; }
  .field.wide-full { flex: 1; min-width: 200px; }

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

  .field-error { font-size: 11px; color: #f87171; }

  .form-actions {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
  }

  button {
    background: #334155;
    color: #f1f5f9;
    border: 1px solid #475569;
    border-radius: 4px;
    padding: 4px 12px;
    font-size: 13px;
    cursor: pointer;
  }
  button:hover   { background: #475569; }
  button.primary { background: #3b82f6; border-color: #2563eb; }
  button.primary:hover { background: #2563eb; }

  .save-btn { align-self: flex-start; }
</style>
