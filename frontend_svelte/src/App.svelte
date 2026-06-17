<script>
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import {
    materials, schema, allSignals,
    room, elements, addElement,
    dataSources, rangeStart, rangeEnd,
    rcResult, rcStatus, rcError,
    theme, saveState, loadState, restoreState,
  } from './lib/store.js';
  import { fetchJson, postRcModel } from './lib/api.js';
  import RoomFields from './lib/RoomFields.svelte';
  import ElementCard from './lib/ElementCard.svelte';
  import DataSources from './lib/DataSources.svelte';
  import PriorBlock from './lib/PriorBlock.svelte';
  import DataPreview from './lib/DataPreview.svelte';

  const PARAM_ORDER = ['H_env', 'H_ve', 'C_wall', 'C_room', 'alpha_eff'];

  let previewComp;
  let themeMenuOpen = false;

  // --- Theme ---
  $: {
    document.documentElement.setAttribute('data-theme', $theme);
    localStorage.setItem('theme', $theme);
  }

  function setTheme(t) {
    theme.set(t);
    themeMenuOpen = false;
  }

  // --- Init ---
  onMount(async () => {
    try {
      const [s, m, sigs] = await Promise.all([
        fetchJson('/api/schema'),
        fetchJson('/api/materials'),
        fetchJson('/api/signals').catch(() => []),
      ]);
      schema.set(s);
      materials.set(m);
      allSignals.set(sigs);
    } catch (e) {
      rcStatus.set(`Failed to load: ${e.message}`);
      rcError.set(true);
      return;
    }

    const saved = loadState();
    const had = restoreState(saved);
    if (!had) addElement();

    // subscribe for auto-compute + save
    room.subscribe(() => { saveState(); scheduleCompute(); });
    elements.subscribe(() => { saveState(); scheduleCompute(); });

    compute();
  });

  // --- Compute priors ---
  let _debounce = null;
  function scheduleCompute() {
    clearTimeout(_debounce);
    _debounce = setTimeout(compute, 180);
  }

  async function compute() {
    const els = get(elements);
    if (!els.length) return;

    const r = get(room);
    const payload = {
      name: r.name,
      floor_area_m2: parseFloat(r.floor_area_m2),
      height_m: parseFloat(r.height_m),
      ach: parseFloat(r.ach),
      latitude: parseFloat(r.latitude),
      longitude: parseFloat(r.longitude),
      elements: els.map(el => ({
        name: el.name,
        type: el.type,
        orientation: el.orientation,
        area_m2: el.area_m2,
        layers: el.layers,
        u_value_override: el.u_value_override ?? null,
      })),
    };

    rcStatus.set('computing…');
    rcError.set(false);
    try {
      const data = await postRcModel(payload);
      rcResult.set(data);
      rcStatus.set('');
    } catch (e) {
      rcStatus.set(e.message);
      rcError.set(true);
    }
  }

  function onDataChange() {
    saveState();
    previewComp?.schedulePreview();
  }

  // Close theme menu on outside click
  function onDocClick(e) {
    if (!e.target.closest('#theme-btn-area')) themeMenuOpen = false;
  }

  // Mermaid
  let mermaidLoaded = false;
  let mermaidDiv;

  onMount(async () => {
    const { default: mermaid } = await import('https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs');
    mermaid.initialize({ startOnLoad: false, theme: $theme === 'dark' ? 'dark' : 'default' });
    window._mermaid = mermaid;
    mermaidLoaded = true;
    renderMermaid();
  });

  async function renderMermaid() {
    if (!window._mermaid || !mermaidDiv) return;
    const source = `graph LR
    Tsa["T_sa(t)<br/>sol-air"]
    Tout["T_out<br/>outdoor"]
    Qint(["Q_int + Q_sol_win"])
    Tsa -->|"R_ext"| Cwall(["C_wall"])
    Cwall -->|"R_int"| Croom(["C_room<br/>room air"])
    Tout -->|"R_ve"| Croom
    Qint --> Croom`;
    mermaidDiv.innerHTML = '';
    const { svg } = await window._mermaid.render('rc-mermaid-' + Date.now(), source);
    mermaidDiv.innerHTML = svg;
  }

  $: if (mermaidLoaded && $theme) {
    window._mermaid?.initialize({ startOnLoad: false, theme: $theme === 'dark' ? 'dark' : 'default' });
    renderMermaid();
  }
</script>

<svelte:document on:click={onDocClick} />

<!-- Topbar -->
<div class="bg-base-200 border-b border-base-300 py-2 px-4 flex items-center justify-between">
  <span class="text-xs tracking-widest uppercase text-base-content/50">thermal nodes</span>
  <div class="flex items-center gap-3">
    <a href="/docs" target="_blank" class="text-xs text-base-content/40 hover:text-base-content/80 transition-colors">API docs</a>
    <div class="relative" id="theme-btn-area">
      <button
        class="text-xs text-base-content/40 hover:text-base-content/80 transition-colors"
        on:click|stopPropagation={() => themeMenuOpen = !themeMenuOpen}
      >theme</button>
      {#if themeMenuOpen}
        <div class="absolute right-0 top-6 z-50 bg-base-200 border border-base-300 rounded shadow-lg py-1 min-w-28">
          <button class="block w-full text-left px-3 py-1 text-xs hover:bg-base-300" on:click={() => setTheme('dark')}>dark</button>
          <button class="block w-full text-left px-3 py-1 text-xs hover:bg-base-300" on:click={() => setTheme('light')}>light</button>
        </div>
      {/if}
    </div>
  </div>
</div>

<!-- Main two-column layout -->
<div style="display:grid; grid-template-columns:380px 1fr; height:calc(100vh - 41px)">

  <!-- Left: editor -->
  <div class="border-r border-base-300 p-3 flex flex-col gap-4 overflow-y-auto">
    <RoomFields />

    <div class="divider my-0"></div>

    <DataSources on:change={onDataChange} />

    <div class="divider my-0"></div>

    <!-- Envelope elements -->
    <div class="flex flex-col gap-2">
      <p class="text-xs uppercase tracking-widest text-base-content/30">Envelope elements</p>
      <div class="flex flex-col gap-2">
        {#each $elements as el (el.id)}
          <ElementCard {el} />
        {/each}
      </div>
      <button class="btn btn-xs btn-outline w-fit"
        on:click={() => { addElement(); scheduleCompute(); }}>+ add element</button>
    </div>
  </div>

  <!-- Right: priors + diagram + data preview -->
  <div class="p-4 overflow-y-auto">

    <!-- RC diagram -->
    <div class="mb-5">
      <p class="text-xs uppercase tracking-widest text-base-content/30 mb-2">RC model</p>
      <div class="flex justify-center" bind:this={mermaidDiv}></div>
    </div>

    <div class="divider my-0 mb-4"></div>

    <p class="text-xs uppercase tracking-widest text-base-content/30 mb-3">RC model priors</p>
    <div class="text-xs mb-2 {$rcError ? 'text-error' : 'text-base-content/30'}">
      {$rcStatus}
    </div>

    <div class="flex flex-col gap-5">
      {#if $rcResult}
        {#each PARAM_ORDER as key}
          {#if $rcResult[key]}
            <PriorBlock p={$rcResult[key]} />
          {/if}
        {/each}
      {/if}
    </div>

    <div class="divider my-4"></div>

    <DataPreview bind:this={previewComp} />
  </div>
</div>
