<script>
  import { onMount, onDestroy } from 'svelte';
  import { get } from 'svelte/store';
  import {
    materials, schema, allSignals,
    room, elements, addElement,
    dataSources, rangeStart, rangeEnd,
    rcResult, rcStatus, rcError,
    theme, navigate,
  } from './store.js';
  import { fetchJson } from './api.js';
  import RoomFields from './RoomFields.svelte';
  import ElementCard from './ElementCard.svelte';
  import DataSources from './DataSources.svelte';
  import PriorBlock from './PriorBlock.svelte';
  import DataPreview from './DataPreview.svelte';

  export let studyId;

  const PARAM_ORDER = ['H_env', 'H_ve', 'C_wall', 'C_room', 'alpha_eff'];

  let previewComp;
  let loadError = '';
  let studyName = '';
  let editingName = false;
  let nameInput = '';

  // --- Load study on mount ---
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
      loadError = `Failed to load schema: ${e.message}`;
      return;
    }

    try {
      const study = await fetchJson(`/api/studies/${studyId}`);
      studyName = study.name;

      if (study.room) {
        room.set({
          name: study.room.name ?? 'Room',
          floor_area_m2: study.room.floor_area_m2,
          height_m: study.room.height_m,
          ach: study.room.ach,
          latitude: study.room.latitude,
          longitude: study.room.longitude,
        });
        // Restore elements from room
        const m2 = get(materials);
        const restored = (study.room.elements ?? []).map((el, i) => ({
          id: i,
          name: el.name,
          type: el.type,
          orientation: el.orientation,
          area_m2: el.area_m2,
          u_value_override: el.u_value_override ?? null,
          layers: el.layers ?? [],
        }));
        elements.set(restored);
      } else {
        addElement();
      }

      if (study.rc_prior) rcResult.set(study.rc_prior);

      if (study.data_spec) {
        if (study.data_spec.signals) dataSources.set(study.data_spec.signals);
        if (study.data_spec.start) rangeStart.set(study.data_spec.start);
        if (study.data_spec.end) rangeEnd.set(study.data_spec.end);
      }
    } catch (e) {
      loadError = `Failed to load study: ${e.message}`;
      return;
    }

    // Subscribe to changes → auto-PATCH
    const unsubs = [
      room.subscribe(() => scheduleRoomPatch()),
      elements.subscribe(() => scheduleRoomPatch()),
    ];
    onDestroy(() => unsubs.forEach(u => u()));

    compute();
  });

  // --- Room patch (debounced) ---
  // Long delay for text/numeric fields (user still typing); short for discrete
  // changes like add/remove element or orientation dropdown.
  let _roomDebounce = null;
  function scheduleRoomPatch(delay = 600) {
    clearTimeout(_roomDebounce);
    _roomDebounce = setTimeout(patchRoom, delay);
  }

  async function patchRoom() {
    const els = get(elements);
    if (!els.length) return;
    const r = get(room);

    const payload = {
      room: {
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
      },
    };

    rcStatus.set('computing…');
    rcError.set(false);
    try {
      const data = await fetch(`/api/studies/${studyId}/room`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!data.ok) throw new Error(`${data.status} ${data.statusText}`);
      rcResult.set(await data.json());
      rcStatus.set('');
    } catch (e) {
      rcStatus.set(e.message);
      rcError.set(true);
    }
  }

  // compute() is an alias for immediate patch
  function compute() { patchRoom(); }

  // --- Data spec patch ---
  async function onDataChange() {
    previewComp?.schedulePreview();
    const spec = {
      data_spec: {
        signals: get(dataSources),
        start: get(rangeStart),
        end: get(rangeEnd),
      },
    };
    try {
      await fetch(`/api/studies/${studyId}/data_spec`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(spec),
      });
    } catch (_) {}
  }

  // --- Name editing ---
  function startEditName() {
    nameInput = studyName;
    editingName = true;
  }

  async function commitName() {
    editingName = false;
    if (nameInput === studyName) return;
    const r = await fetch(`/api/studies/${studyId}/name`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: nameInput }),
    });
    if (r.ok) studyName = nameInput;
  }

  // --- Mermaid ---
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

<!-- Editor layout -->
<div style="display:grid; grid-template-columns:380px 1fr; height:calc(100vh - 41px)">

  <!-- Left: editor -->
  <div class="border-r border-base-300 p-3 flex flex-col gap-4 overflow-y-auto">

    <!-- Study name -->
    <div class="flex items-center gap-2">
      {#if editingName}
        <input
          class="input input-xs flex-1 font-mono"
          bind:value={nameInput}
          on:blur={commitName}
          on:keydown={(e) => { if (e.key === 'Enter') commitName(); if (e.key === 'Escape') editingName = false; }}
          autofocus
        />
      {:else}
        <button
          class="flex-1 text-left text-xs font-mono text-base-content/60 hover:text-primary truncate"
          on:click={startEditName}
          title="Click to rename"
        >{studyName || '…'}</button>
      {/if}
    </div>

    {#if loadError}
      <div class="alert alert-error text-xs">{loadError}</div>
    {/if}

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
        on:click={() => { addElement(); scheduleRoomPatch(0); }}>+ add element</button>
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

    <DataPreview bind:this={previewComp} {studyId} />
  </div>
</div>
