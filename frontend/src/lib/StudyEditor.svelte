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
  import FitResultChart from './FitResultChart.svelte';

  export let studyId;

  const PARAM_ORDER = ['H_env', 'H_ve', 'C_wall', 'C_room', 'alpha_eff'];
  const PARAM_UNITS = { H_env: 'W/K', H_ve: 'W/K', C_wall: 'MJ/K', C_room: 'MJ/K', alpha_eff: '—' };
  const PARAM_SCALE = { H_env: 1, H_ve: 1, C_wall: 1e-6, C_room: 1e-6, alpha_eff: 1 };

  let loadError = '';
  let studyName = '';
  let editingName = false;
  let nameInput = '';

  let inputData = null;   // cached from study.input_data or after fetch
  let fitResult = null;
  let fitting = false;
  let fitStatus = '';

  // T_int pairs for fit chart (aligned timestamps)
  $: tObsPairs = (() => {
    if (!inputData || !$dataSources) return null;
    const sig = $dataSources['T_int'];
    return sig && inputData[sig] ? inputData[sig] : null;
  })();

  // --- Load study on mount ---
  // Set up subscriptions synchronously so onDestroy works correctly.
  // Guard with a flag so they don't fire before the study is fully loaded.
  let _loaded = false;
  const _unsubs = [
    room.subscribe(() => { if (_loaded) scheduleRoomPatch(); }),
    elements.subscribe(() => { if (_loaded) scheduleRoomPatch(); }),
  ];
  onDestroy(() => _unsubs.forEach(u => u()));

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
        if (study.data_spec.signals) dataSources.update(defaults => ({ ...defaults, ...study.data_spec.signals }));
        if (study.data_spec.start) rangeStart.set(study.data_spec.start);
        if (study.data_spec.end) rangeEnd.set(study.data_spec.end);
      }

      if (study.input_data) inputData = study.input_data;
      if (study.fit_result) fitResult = study.fit_result;
    } catch (e) {
      loadError = `Failed to load study: ${e.message}`;
      return;
    }

    _loaded = true;
    compute();
  });

  // --- Room patch (debounced) ---
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

  function compute() { patchRoom(); }

  // --- Data spec patch ---
  async function onDataChange() {
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

  // Called when DataSources emits 'fetched'
  function onFetched(e) {
    inputData = e.detail;
    fitResult = null; // stale fit after new data
    fitStatus = '';
  }

  // --- Fit ---
  async function runFit() {
    fitting = true;
    fitStatus = 'running…';
    try {
      const r = await fetch(`/api/studies/${studyId}/fit`, { method: 'POST' });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        fitStatus = `error: ${err.detail ?? r.statusText}`;
        return;
      }
      fitResult = await r.json();
      fitStatus = fitResult.success
        ? `RMSE ${fitResult.residual_rmse?.toFixed(3)} °C · ${fitResult.n_obs} obs`
        : `converged with warning: ${fitResult.message}`;
    } catch (e) {
      fitStatus = `error: ${e.message}`;
    } finally {
      fitting = false;
    }
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

    <DataSources {studyId} on:change={onDataChange} on:fetched={onFetched} />

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

  <!-- Right: priors + diagram + data preview + fit -->
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

    <DataPreview {inputData} dataSources={$dataSources} />

    <div class="divider my-4"></div>

    <!-- Fit section -->
    <div>
      <p class="text-xs uppercase tracking-widest text-base-content/30 mb-3">Bayesian fit</p>
      <div class="flex items-center gap-3 mb-3">
        <button
          class="btn btn-xs btn-outline"
          class:loading={fitting}
          disabled={fitting || !inputData}
          on:click={runFit}
        >
          {fitting ? 'fitting…' : 'Run fit'}
        </button>
        {#if fitStatus}
          <span class="text-xs text-base-content/40">{fitStatus}</span>
        {/if}
      </div>

      {#if fitResult}
        <!-- Parameter table: param | prior mu ± σ | posterior -->
        <table class="text-xs font-mono w-full mb-4" style="border-collapse:collapse">
          <thead>
            <tr class="text-base-content/30 text-left">
              <th class="pr-4 pb-1 font-normal">param</th>
              <th class="pr-4 pb-1 font-normal">unit</th>
              <th class="pr-4 pb-1 font-normal">prior μ ± σ</th>
              <th class="pr-4 pb-1 font-normal">posterior</th>
              <th class="pb-1 font-normal text-right">shift (σ)</th>
            </tr>
          </thead>
          <tbody>
            {#each PARAM_ORDER as k}
              {@const scale = PARAM_SCALE[k]}
              {@const unit  = PARAM_UNITS[k]}
              {@const prior = $rcResult?.[k]}
              {@const post  = fitResult[k]}
              {@const shift = (prior && typeof post === 'number' && prior.sigma > 0)
                ? (post - prior.mu) / prior.sigma
                : null}
              {@const shiftColor = shift === null ? ''
                : Math.abs(shift) < 1 ? 'text-base-content/40'
                : Math.abs(shift) < 2 ? 'text-warning'
                : 'text-error'}
              <tr class="border-t border-base-300/40">
                <td class="pr-4 py-0.5 text-base-content/50">{k}</td>
                <td class="pr-4 py-0.5 text-base-content/30">{unit}</td>
                <td class="pr-4 py-0.5 text-base-content/40">
                  {#if prior}
                    {(prior.mu * scale).toPrecision(3)} ± {(prior.sigma * scale).toPrecision(2)}
                  {:else}—{/if}
                </td>
                <td class="pr-4 py-0.5 text-base-content/70 font-semibold">
                  {typeof post === 'number' ? (post * scale).toPrecision(4) : '—'}
                </td>
                <td class="py-0.5 text-right {shiftColor}">
                  {shift !== null ? (shift > 0 ? '+' : '') + shift.toFixed(2) : '—'}
                </td>
              </tr>
            {/each}
            {#if fitResult.alpha_by_orient && Object.keys(fitResult.alpha_by_orient).length > 1}
              {#each Object.entries(fitResult.alpha_by_orient) as [orient, alpha]}
                <tr class="border-t border-base-300/20">
                  <td class="pr-4 py-0.5 text-base-content/40 pl-3">α_{orient}</td>
                  <td class="pr-4 py-0.5 text-base-content/30">—</td>
                  <td class="pr-4 py-0.5 text-base-content/30">—</td>
                  <td class="pr-4 py-0.5 text-base-content/60 font-semibold">
                    {typeof alpha === 'number' ? alpha.toPrecision(3) : '—'}
                  </td>
                  <td></td>
                </tr>
              {/each}
            {/if}
            {#each [['T_wall_0', 'T_wall₀'], ['T_room_0', 'T_room₀']] as [key, label]}
              <tr class="border-t border-base-300/40">
                <td class="pr-4 py-0.5 text-base-content/50">{label}</td>
                <td class="pr-4 py-0.5 text-base-content/30">°C</td>
                <td class="pr-4 py-0.5 text-base-content/40">—</td>
                <td class="pr-4 py-0.5 text-base-content/70 font-semibold">
                  {typeof fitResult[key] === 'number' ? fitResult[key].toFixed(2) : '—'}
                </td>
                <td></td>
              </tr>
            {/each}
            <tr class="border-t border-base-300/40">
              <td class="pr-4 py-0.5 text-base-content/30" colspan="3">RMSE</td>
              <td class="py-0.5 text-base-content/70">{fitResult.residual_rmse?.toFixed(3)} °C</td>
              <td></td>
            </tr>
            <tr>
              <td class="pr-4 py-0.5 text-base-content/30" colspan="3">n obs</td>
              <td class="py-0.5 text-base-content/70">{fitResult.n_obs}</td>
              <td></td>
            </tr>
          </tbody>
        </table>

        <!-- Fit chart: T_obs / T_room_pred / T_wall_pred + residuals -->
        <FitResultChart {fitResult} {tObsPairs} />
      {/if}
    </div>
  </div>
</div>
