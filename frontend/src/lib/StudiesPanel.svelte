<script>
  import { studies, activeStudy, addStudy, updateStudy, removeStudy, clearResults, runSimulate } from '../stores/studies.js';

  /** @type {string} */
  export let modelId;

  // ---------------------------------------------------------------------------
  // Panel-local async state (separate from the shared model loading store)
  // ---------------------------------------------------------------------------

  let panelLoading = false;
  let panelError   = '';

  async function withPanelLoading(fn) {
    panelLoading = true;
    panelError   = '';
    try {
      return await fn();
    } catch (err) {
      panelError = err.message ?? String(err);
      throw err;
    } finally {
      panelLoading = false;
    }
  }

  // ---------------------------------------------------------------------------
  // "Load study" modal open/close
  // ---------------------------------------------------------------------------

  let loadModalOpen = false;

  function openLoadModal() { loadModalOpen = true; }
  function closeLoadModal() { loadModalOpen = false; }

  function selectStudyFromModal(study) {
    selectStudy(study);
    closeLoadModal();
  }

  // ---------------------------------------------------------------------------
  // "+ New study" dropdown
  // ---------------------------------------------------------------------------

  let newStudyDropdownOpen = false;

  function toggleNewStudyDropdown() {
    newStudyDropdownOpen = !newStudyDropdownOpen;
  }

  function closeNewStudyDropdown() {
    newStudyDropdownOpen = false;
  }

  async function handleNewStudy() {
    closeNewStudyDropdown();
    const created = await withPanelLoading(() => addStudy(modelId));
    // created is the server study object; _kind defaults to 'real' (not set)
    return created;
  }

  async function handleNewSyntheticStudy() {
    closeNewStudyDropdown();
    const created = await withPanelLoading(() => addStudy(modelId));
    // Tag client-only — do NOT PATCH to server
    activeStudy.update(s => s?.uid === created.uid ? { ...s, _kind: 'synthetic' } : s);
  }

  // ---------------------------------------------------------------------------
  // Study list actions
  // ---------------------------------------------------------------------------

  async function selectStudy(study) {
    activeStudy.set(study);
    // Reset local edit state when switching studies
    editName     = study.name;
    editStart    = study.time_range?.start ? isoToDateStr(study.time_range.start) : '';
    editEnd      = study.time_range?.end   ? isoToDateStr(study.time_range.end)   : '';
    editNDays    = defaultNDays;
    dateMode     = 'start+days';
    confirmDelete = false;
  }

  // ---------------------------------------------------------------------------
  // Reactive: keep local edit fields in sync when activeStudy changes from
  // outside (e.g. loadStudies re-populates the store after a run).
  // ---------------------------------------------------------------------------

  let editName      = '';
  let editStart     = '';
  let editEnd       = '';
  /** Number of days for "Start + days" mode. */
  let editNDays     = 7;
  const defaultNDays = 7;

  /**
   * Which date-range input mode is active.
   * 'start+end'  — two date pickers (start + end)
   * 'start+days' — one date picker + number of days
   */
  let dateMode = 'start+days';

  let confirmDelete = false;

  $: if ($activeStudy) {
    editName  = $activeStudy.name;
    editStart = $activeStudy.time_range?.start ? isoToDateStr($activeStudy.time_range.start) : '';
    editEnd   = $activeStudy.time_range?.end   ? isoToDateStr($activeStudy.time_range.end)   : '';
    // Don't reset editNDays / dateMode here — let them persist across rerenders
    // caused by result updates so the user's chosen mode is not disrupted.
  }

  // ---------------------------------------------------------------------------
  // Date helpers
  // ---------------------------------------------------------------------------

  /** Convert "YYYY-MM-DD" to UTC midnight ISO-8601. */
  function dateToUTCIso(dateStr) {
    return `${dateStr}T00:00:00Z`;
  }

  /** Extract "YYYY-MM-DD" from an ISO-8601 string. */
  function isoToDateStr(iso) {
    return iso ? iso.slice(0, 10) : '';
  }

  /** Format an ISO timestamp for display (date + time, UTC). */
  function formatTimestamp(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toISOString().replace('T', ' ').slice(0, 16) + ' UTC';
  }

  /** Format an ISO timestamp as a short date for list display. */
  function formatDate(iso) {
    if (!iso) return '';
    return iso.slice(0, 10);
  }

  /**
   * Add N calendar days to a "YYYY-MM-DD" string (UTC) and return the result.
   * @param {string} dateStr  "YYYY-MM-DD"
   * @param {number} nDays
   * @returns {string} "YYYY-MM-DD"
   */
  function addDays(dateStr, nDays) {
    const d = new Date(`${dateStr}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() + nDays);
    return d.toISOString().slice(0, 10);
  }

  // ---------------------------------------------------------------------------
  // Detail form — patch on blur / Enter for name; patch on change for dates
  // ---------------------------------------------------------------------------

  async function saveName() {
    if (!$activeStudy || editName === $activeStudy.name) return;
    await withPanelLoading(() => updateStudy(modelId, $activeStudy.uid, { name: editName }));
  }

  function handleNameKeydown(e) {
    if (e.key === 'Enter') e.target.blur();
  }

  async function saveTimeRange() {
    if (!$activeStudy) return;
    let start = editStart;
    let end   = editEnd;

    if (dateMode === 'start+days') {
      if (!editStart || !editNDays || editNDays < 1) return;
      end = addDays(editStart, editNDays);
    } else {
      if (!start || !end) return;
    }

    const time_range = {
      start:    dateToUTCIso(start),
      end:      dateToUTCIso(end),
      resample: '15min',
    };
    await withPanelLoading(() => updateStudy(modelId, $activeStudy.uid, { time_range }));
  }

  // ---------------------------------------------------------------------------
  // Run simulation
  // ---------------------------------------------------------------------------

  let runLoading = false;
  let runError   = '';

  $: canRun = $activeStudy?.time_range?.start && $activeStudy?.time_range?.end;
  $: hasResults = !!$activeStudy?.results?.simulate;

  async function handleRunSimulate() {
    if (!$activeStudy) return;
    runLoading = true;
    runError   = '';
    try {
      await runSimulate(modelId, $activeStudy.uid);
    } catch (err) {
      runError = err.message ?? String(err);
    } finally {
      runLoading = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Clear results
  // ---------------------------------------------------------------------------

  async function handleClearResults() {
    if (!$activeStudy) return;
    await withPanelLoading(() => clearResults(modelId, $activeStudy.uid));
  }

  // ---------------------------------------------------------------------------
  // Delete study
  // ---------------------------------------------------------------------------

  async function handleDelete() {
    if (!$activeStudy) return;
    if (!confirmDelete) {
      confirmDelete = true;
      return;
    }
    await withPanelLoading(() => removeStudy(modelId, $activeStudy.uid));
    confirmDelete = false;
  }

  // ---------------------------------------------------------------------------
  // SVG line chart — identical constants and logic as SimulationPanel.svelte
  // ---------------------------------------------------------------------------

  const CHART_W = 560;
  const CHART_H = 200;
  const PAD = { top: 16, right: 16, bottom: 36, left: 44 };
  const INNER_W = CHART_W - PAD.left - PAD.right;
  const INNER_H = CHART_H - PAD.top  - PAD.bottom;

  const LINE_COLORS = ['oklch(55% 0.18 250)', 'oklch(60% 0.18 40)'];
  const SENSOR_COLORS = ['oklch(50% 0.18 145)', 'oklch(55% 0.18 310)'];

  $: chartData = computeChartData($activeStudy?.results?.simulate ?? null);

  function computeChartData(result) {
    if (!result?.t?.length) return null;

    const t          = result.t;
    const names      = Object.keys(result.states);
    const obsEntries = Object.entries(result.observations ?? {});

    const stateValues = names.flatMap(n => result.states[n]);
    const obsValues   = obsEntries.flatMap(([, vals]) => vals);
    const allValues   = [...stateValues, ...obsValues];

    const tMin = t[0];
    const tMax = t[t.length - 1];
    const vMin = Math.min(...allValues);
    const vMax = Math.max(...allValues);
    const vPad = (vMax - vMin) * 0.05 || 1;

    const scaleX = v => PAD.left + ((v - tMin) / (tMax - tMin || 1)) * INNER_W;
    const scaleY = v => PAD.top + INNER_H - ((v - (vMin - vPad)) / ((vMax + vPad) - (vMin - vPad))) * INNER_H;

    const series = names.map((name, ci) => {
      const pts = t.map((tv, i) => [scaleX(tv), scaleY(result.states[name][i])]);
      return {
        name,
        color: LINE_COLORS[ci % LINE_COLORS.length],
        path: pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' '),
      };
    });

    const sensorSeries = obsEntries.map(([sensorName, vals], ci) => {
      const pts = t.map((tv, i) => [scaleX(tv), scaleY(vals[i])]);
      return {
        name: sensorName,
        color: SENSOR_COLORS[ci % SENSOR_COLORS.length],
        path: pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' '),
      };
    });

    // Y-axis ticks
    const nTicks = 4;
    const yTicks = Array.from({ length: nTicks + 1 }, (_, i) => {
      const v = (vMin - vPad) + i * ((vMax + vPad) - (vMin - vPad)) / nTicks;
      return { v: v.toFixed(1), y: scaleY(v) };
    });

    // X-axis ticks: t is seconds from epoch for study (bound) results
    const nXTicks = 6;
    const xTicks = Array.from({ length: nXTicks + 1 }, (_, i) => {
      const tv = tMin + i * (tMax - tMin) / nXTicks;
      const d = new Date(tv * 1000);
      const label = `${String(d.getUTCDate()).padStart(2,'0')}/${String(d.getUTCMonth() + 1).padStart(2,'0')} ${String(d.getUTCHours()).padStart(2,'0')}h`;
      return { label, x: scaleX(tv) };
    });

    // Residuals: for each sensor series, find the matching simulated state.
    const stateKeys = Object.keys(result.states);
    const residualSeries = obsEntries.map(([sensorName, obsVals], ci) => {
      const matchedState =
        result.states[sensorName] ??
        result.states['T_room'] ??
        result.states[stateKeys[0]];
      if (!matchedState) return null;
      const residuals = obsVals.map((o, i) => o - matchedState[i]);
      return { name: sensorName, color: SENSOR_COLORS[ci % SENSOR_COLORS.length], residuals };
    }).filter(Boolean);

    let residualsChart = null;
    if (residualSeries.length > 0) {
      const allRes = residualSeries.flatMap(s => s.residuals);
      const rMin = Math.min(...allRes);
      const rMax = Math.max(...allRes);
      const rPad = (rMax - rMin) * 0.1 || 0.5;
      const rLo  = rMin - rPad;
      const rHi  = rMax + rPad;

      const scaleRY = v => PAD.top + INNER_H - ((v - rLo) / (rHi - rLo)) * INNER_H;
      const zeroY   = scaleRY(0);

      const rYTicks = Array.from({ length: 5 }, (_, i) => {
        const v = rLo + i * (rHi - rLo) / 4;
        return { v: v.toFixed(2), y: scaleRY(v) };
      });

      const rLines = residualSeries.map(s => {
        const pts = t.map((tv, i) => [scaleX(tv), scaleRY(s.residuals[i])]);
        return {
          name: s.name,
          color: s.color,
          path: pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' '),
        };
      });

      residualsChart = { rLines, rYTicks, xTicks, zeroY };
    }

    return { series, sensorSeries, yTicks, xTicks, residualsChart };
  }
</script>

<!-- ============================================================
     "Load study" modal (DaisyUI dialog)
============================================================ -->
{#if loadModalOpen}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_noninteractive_element_interactions -->
  <dialog
    class="modal modal-open"
    aria-label="Load study"
    onclick={(e) => { if (e.target === e.currentTarget) closeLoadModal(); }}
  >
    <div class="modal-box max-w-sm">
      <h3 class="font-semibold text-base mb-3">Load study</h3>

      {#if $studies.length === 0}
        <p class="text-sm text-base-content/50 py-4 text-center">No studies yet.</p>
      {:else}
        <ul class="space-y-1" role="listbox" aria-label="Available studies">
          {#each $studies as study (study.uid)}
            <li>
              <button
                class="w-full text-left px-3 py-2 rounded-lg hover:bg-base-200 flex items-center justify-between gap-2
                  {$activeStudy?.uid === study.uid ? 'bg-base-200 font-medium' : ''}"
                role="option"
                aria-selected={$activeStudy?.uid === study.uid}
                onclick={() => selectStudyFromModal(study)}
              >
                <span class="flex flex-col gap-0.5 min-w-0">
                  <span class="text-sm truncate">{study.name}</span>
                  <span class="text-xs text-base-content/50">{formatDate(study.created_at)}</span>
                </span>
                {#if study.results?.simulate}
                  <span class="badge badge-success badge-xs shrink-0">results</span>
                {/if}
              </button>
            </li>
          {/each}
        </ul>
      {/if}

      <div class="modal-action mt-4">
        <button class="btn btn-ghost btn-sm" onclick={closeLoadModal}>Close</button>
      </div>
    </div>
  </dialog>
{/if}

<!-- ============================================================
     Main panel layout
============================================================ -->
<div class="flex flex-col h-full overflow-hidden">

  <!-- ---- Top bar ---- -->
  <div class="flex items-center gap-2 px-4 py-2 border-b border-base-300 shrink-0">

    <!-- Study name — ghost/transparent inline input, auto-saves on blur/Enter -->
    {#if $activeStudy}
      <input
        type="text"
        class="input input-ghost input-sm flex-1 min-w-0 font-medium focus:bg-base-200"
        bind:value={editName}
        onblur={saveName}
        onkeydown={handleNameKeydown}
        disabled={panelLoading}
        aria-label="Study name"
        placeholder="Study name"
      />
    {:else}
      <span class="flex-1 text-sm text-base-content/40 italic px-1">No study selected</span>
    {/if}

    <!-- "Load study" button -->
    <button
      class="btn btn-ghost btn-sm shrink-0"
      onclick={openLoadModal}
      aria-label="Load an existing study"
      title="Load study"
    >
      Load
    </button>

    <!-- "+ New study" dropdown -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="relative shrink-0">
      <button
        class="btn btn-primary btn-sm"
        onclick={toggleNewStudyDropdown}
        disabled={panelLoading}
        aria-haspopup="true"
        aria-expanded={newStudyDropdownOpen}
        aria-label="Create a new study"
      >
        {#if panelLoading && !$activeStudy}
          <span class="loading loading-spinner loading-xs"></span>
        {/if}
        + New study
        <!-- Chevron icon -->
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3 ml-0.5" aria-hidden="true">
          <path fill-rule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
        </svg>
      </button>

      {#if newStudyDropdownOpen}
        <!-- Click-outside overlay -->
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <div
          class="fixed inset-0 z-10"
          role="presentation"
          onclick={closeNewStudyDropdown}
        ></div>
        <ul class="absolute right-0 top-full mt-1 z-20 menu menu-sm bg-base-100 border border-base-300 rounded-lg shadow-lg w-44 p-1">
          <li>
            <button onclick={handleNewStudy} class="text-left">
              Real-data
            </button>
          </li>
          <li>
            <button onclick={handleNewSyntheticStudy} class="text-left">
              Synthetic <span class="text-base-content/40 text-xs">(stub)</span>
            </button>
          </li>
        </ul>
      {/if}
    </div>

  </div>

  <!-- Panel-level error -->
  {#if panelError}
    <div role="alert" class="alert alert-error text-sm py-2 mx-4 mt-2 shrink-0">
      <span>{panelError}</span>
    </div>
  {/if}

  <!-- ---- Content area ---- -->
  <div class="flex-1 overflow-y-auto">

    {#if $studies.length === 0}
      <!-- Empty state -->
      <div class="flex items-center justify-center h-full py-16 px-6 text-center text-base-content/40 text-sm">
        No studies yet. Use '+ New study' to create one.
      </div>

    {:else if !$activeStudy}
      <!-- Has studies but none selected -->
      <div class="flex items-center justify-center h-full py-16 px-6 text-center text-base-content/40 text-sm">
        Select a study using "Load" or create a new one.
      </div>

    {:else if $activeStudy._kind === 'synthetic'}
      <!-- Synthetic study placeholder -->
      <div class="p-4 space-y-4">
        <div class="rounded-lg bg-base-200 border border-base-300 p-6 text-center space-y-2">
          <p class="text-sm font-medium text-base-content/70">Synthetic study</p>
          <p class="text-sm text-base-content/50">
            Synthetic studies are not yet implemented. Coming soon.
          </p>
        </div>

        <!-- Delete -->
        <div class="border-t border-base-300 pt-4">
          {#if confirmDelete}
            <p class="text-sm text-error mb-2">Delete "{$activeStudy.name}"? This cannot be undone.</p>
            <div class="flex gap-2">
              <button class="btn btn-error btn-sm" onclick={handleDelete} disabled={panelLoading}>
                {#if panelLoading}<span class="loading loading-spinner loading-xs"></span>{/if}
                Confirm delete
              </button>
              <button class="btn btn-ghost btn-sm" onclick={() => { confirmDelete = false; }} disabled={panelLoading}>Cancel</button>
            </div>
          {:else}
            <button class="btn btn-ghost btn-sm text-error" onclick={handleDelete} disabled={panelLoading}>
              Delete study
            </button>
          {/if}
        </div>
      </div>

    {:else}
      <!-- Real-data study detail -->
      <div class="p-4 space-y-4">

        <!-- Compact time range controls -->
        <div class="space-y-2">

          <!-- Mode toggle (segmented control) -->
          <div class="join" role="group" aria-label="Date range input mode">
            <button
              class="join-item btn btn-xs {dateMode === 'start+end' ? 'btn-primary' : 'btn-outline'}"
              onclick={() => { dateMode = 'start+end'; }}
              aria-pressed={dateMode === 'start+end'}
            >
              Start / End
            </button>
            <button
              class="join-item btn btn-xs {dateMode === 'start+days' ? 'btn-primary' : 'btn-outline'}"
              onclick={() => { dateMode = 'start+days'; }}
              aria-pressed={dateMode === 'start+days'}
            >
              Start + days
            </button>
          </div>

          {#if dateMode === 'start+end'}
            <!-- Start / End mode -->
            <div class="flex gap-2 flex-wrap">
              <div class="form-control flex-1 min-w-[8rem]">
                <label class="label py-0.5" for="study-start">
                  <span class="label-text text-xs">Start (UTC)</span>
                </label>
                <input
                  id="study-start"
                  type="date"
                  class="input input-bordered input-sm"
                  bind:value={editStart}
                  onchange={saveTimeRange}
                  disabled={panelLoading}
                />
              </div>
              <div class="form-control flex-1 min-w-[8rem]">
                <label class="label py-0.5" for="study-end">
                  <span class="label-text text-xs">End (UTC)</span>
                </label>
                <input
                  id="study-end"
                  type="date"
                  class="input input-bordered input-sm"
                  bind:value={editEnd}
                  onchange={saveTimeRange}
                  disabled={panelLoading}
                />
              </div>
            </div>

          {:else}
            <!-- Start + N days mode -->
            <div class="flex gap-2 flex-wrap">
              <div class="form-control flex-1 min-w-[8rem]">
                <label class="label py-0.5" for="study-start-days">
                  <span class="label-text text-xs">Start (UTC)</span>
                </label>
                <input
                  id="study-start-days"
                  type="date"
                  class="input input-bordered input-sm"
                  bind:value={editStart}
                  onchange={saveTimeRange}
                  disabled={panelLoading}
                />
              </div>
              <div class="form-control w-24">
                <label class="label py-0.5" for="study-ndays">
                  <span class="label-text text-xs">Days</span>
                </label>
                <input
                  id="study-ndays"
                  type="number"
                  min="1"
                  class="input input-bordered input-sm"
                  bind:value={editNDays}
                  onchange={saveTimeRange}
                  disabled={panelLoading}
                />
              </div>
            </div>
          {/if}

          {#if dateMode === 'start+end' && (!editStart || !editEnd)}
            <p class="text-xs text-warning">Set start and end dates before running the simulation.</p>
          {:else if dateMode === 'start+days' && (!editStart || !editNDays || editNDays < 1)}
            <p class="text-xs text-warning">Set a start date and number of days before running.</p>
          {/if}
        </div>

        <!-- Run / clear actions -->
        <div class="flex flex-wrap gap-2 items-center">
          <button
            class="btn btn-accent btn-sm"
            onclick={handleRunSimulate}
            disabled={runLoading || panelLoading || !canRun}
            title={!canRun ? 'Set time range first' : 'Run simulation for this study'}
          >
            {#if runLoading}
              <span class="loading loading-spinner loading-xs"></span>
            {/if}
            Run simulation
          </button>

          {#if hasResults}
            <button
              class="btn btn-outline btn-sm"
              onclick={handleClearResults}
              disabled={panelLoading}
              title="Clear stored simulation results"
            >
              Clear results
            </button>
          {/if}
        </div>

        <!-- Run error -->
        {#if runError}
          <div role="alert" class="alert alert-error text-sm py-2">
            <span>{runError}</span>
          </div>
        {/if}

        <!-- Simulation results -->
        {#if $activeStudy.results?.simulate}
          {@const sim = $activeStudy.results.simulate}
          <section aria-label="Simulation results">
            <div class="flex items-center gap-3 mb-2">
              <span class="badge badge-accent badge-sm">Simulation result</span>
              <span class="text-xs text-base-content/50">
                Ran {formatTimestamp(sim.ran_at)}
              </span>
              <span class="text-xs text-base-content/50">
                {editStart} → {editEnd}
              </span>
            </div>

            {#if chartData}
              <div class="border border-base-300 rounded-lg p-2 overflow-x-auto">
                <svg
                  viewBox="0 0 {CHART_W} {CHART_H}"
                  width="100%"
                  style="max-width: {CHART_W}px;"
                  role="img"
                  aria-label="Simulated temperature trajectories over the study time range"
                >
                  <!-- Y grid lines + labels -->
                  {#each chartData.yTicks as tick}
                    <line
                      x1={PAD.left} y1={tick.y}
                      x2={PAD.left + INNER_W} y2={tick.y}
                      stroke="oklch(80% 0 0)" stroke-width="0.5"
                    />
                    <text
                      x={PAD.left - 4} y={tick.y + 4}
                      text-anchor="end"
                      font-size="9"
                      fill="oklch(50% 0 0)"
                    >{tick.v}</text>
                  {/each}

                  <!-- X axis ticks + labels -->
                  {#each chartData.xTicks as tick}
                    <line
                      x1={tick.x} y1={PAD.top + INNER_H}
                      x2={tick.x} y2={PAD.top + INNER_H + 4}
                      stroke="oklch(60% 0 0)" stroke-width="1"
                    />
                    <text
                      x={tick.x} y={PAD.top + INNER_H + 14}
                      text-anchor="middle"
                      font-size="9"
                      fill="oklch(50% 0 0)"
                    >{tick.label}</text>
                  {/each}

                  <!-- Axis labels -->
                  <text
                    x={PAD.left + INNER_W / 2}
                    y={CHART_H - 2}
                    text-anchor="middle"
                    font-size="10"
                    fill="oklch(40% 0 0)"
                  >Date/time</text>
                  <text
                    x={10}
                    y={PAD.top + INNER_H / 2}
                    text-anchor="middle"
                    font-size="10"
                    fill="oklch(40% 0 0)"
                    transform="rotate(-90, 10, {PAD.top + INNER_H / 2})"
                  >Temperature (°C)</text>

                  <!-- Clip path for lines -->
                  <defs>
                    <clipPath id="study-chart-clip">
                      <rect x={PAD.left} y={PAD.top} width={INNER_W} height={INNER_H} />
                    </clipPath>
                  </defs>

                  <!-- Series lines -->
                  <g clip-path="url(#study-chart-clip)">
                    {#each chartData.series as s}
                      <path
                        d={s.path}
                        fill="none"
                        stroke={s.color}
                        stroke-width="2"
                        stroke-linejoin="round"
                      />
                    {/each}
                    {#each chartData.sensorSeries as s}
                      <path
                        d={s.path}
                        fill="none"
                        stroke={s.color}
                        stroke-width="1.5"
                        stroke-dasharray="4 3"
                        stroke-linejoin="round"
                      />
                    {/each}
                  </g>

                  <!-- Axes -->
                  <line
                    x1={PAD.left} y1={PAD.top}
                    x2={PAD.left} y2={PAD.top + INNER_H}
                    stroke="oklch(40% 0 0)" stroke-width="1"
                  />
                  <line
                    x1={PAD.left} y1={PAD.top + INNER_H}
                    x2={PAD.left + INNER_W} y2={PAD.top + INNER_H}
                    stroke="oklch(40% 0 0)" stroke-width="1"
                  />

                  <!-- Legend -->
                  {#each chartData.series as s, i}
                    <g transform="translate({PAD.left + i * 100}, 6)">
                      <line x1="0" y1="6" x2="18" y2="6" stroke={s.color} stroke-width="2"/>
                      <text x="22" y="10" font-size="10" fill="oklch(40% 0 0)" font-family="ui-monospace, monospace">
                        {s.name}
                      </text>
                    </g>
                  {/each}
                  {#each chartData.sensorSeries as s, i}
                    <g transform="translate({PAD.left + (chartData.series.length + i) * 100}, 6)">
                      <line x1="0" y1="6" x2="18" y2="6" stroke={s.color} stroke-width="1.5" stroke-dasharray="4 3"/>
                      <text x="22" y="10" font-size="10" fill="oklch(40% 0 0)" font-family="ui-monospace, monospace">
                        {s.name}
                      </text>
                    </g>
                  {/each}
                </svg>
              </div>

              {#if chartData.residualsChart}
                {@const rc = chartData.residualsChart}
                <div class="border border-base-300 rounded-lg p-2 overflow-x-auto mt-3">
                  <div class="flex items-center gap-2 mb-1 px-1">
                    <span class="badge badge-outline badge-xs">Residuals (observed − simulated)</span>
                  </div>
                  <svg
                    viewBox="0 0 {CHART_W} {CHART_H}"
                    width="100%"
                    style="max-width: {CHART_W}px;"
                    role="img"
                    aria-label="Residuals: observed minus simulated temperature"
                  >
                    <!-- Y grid lines + labels -->
                    {#each rc.rYTicks as tick}
                      <line
                        x1={PAD.left} y1={tick.y}
                        x2={PAD.left + INNER_W} y2={tick.y}
                        stroke="oklch(80% 0 0)" stroke-width="0.5"
                      />
                      <text
                        x={PAD.left - 4} y={tick.y + 4}
                        text-anchor="end"
                        font-size="9"
                        fill="oklch(50% 0 0)"
                      >{tick.v}</text>
                    {/each}

                    <!-- Zero reference line -->
                    <line
                      x1={PAD.left} y1={rc.zeroY}
                      x2={PAD.left + INNER_W} y2={rc.zeroY}
                      stroke="oklch(50% 0 0)" stroke-width="1" stroke-dasharray="4 3"
                    />

                    <!-- X axis ticks + labels -->
                    {#each rc.xTicks as tick}
                      <line
                        x1={tick.x} y1={PAD.top + INNER_H}
                        x2={tick.x} y2={PAD.top + INNER_H + 4}
                        stroke="oklch(60% 0 0)" stroke-width="1"
                      />
                      <text
                        x={tick.x} y={PAD.top + INNER_H + 14}
                        text-anchor="middle"
                        font-size="9"
                        fill="oklch(50% 0 0)"
                      >{tick.label}</text>
                    {/each}

                    <!-- Axis labels -->
                    <text
                      x={PAD.left + INNER_W / 2}
                      y={CHART_H - 2}
                      text-anchor="middle"
                      font-size="10"
                      fill="oklch(40% 0 0)"
                    >Date/time</text>
                    <text
                      x={10}
                      y={PAD.top + INNER_H / 2}
                      text-anchor="middle"
                      font-size="10"
                      fill="oklch(40% 0 0)"
                      transform="rotate(-90, 10, {PAD.top + INNER_H / 2})"
                    >Residual (°C)</text>

                    <!-- Clip path for residual lines -->
                    <defs>
                      <clipPath id="study-residuals-clip">
                        <rect x={PAD.left} y={PAD.top} width={INNER_W} height={INNER_H} />
                      </clipPath>
                    </defs>

                    <!-- Residual lines -->
                    <g clip-path="url(#study-residuals-clip)">
                      {#each rc.rLines as s}
                        <path
                          d={s.path}
                          fill="none"
                          stroke={s.color}
                          stroke-width="1.5"
                          stroke-linejoin="round"
                        />
                      {/each}
                    </g>

                    <!-- Axes -->
                    <line
                      x1={PAD.left} y1={PAD.top}
                      x2={PAD.left} y2={PAD.top + INNER_H}
                      stroke="oklch(40% 0 0)" stroke-width="1"
                    />
                    <line
                      x1={PAD.left} y1={PAD.top + INNER_H}
                      x2={PAD.left + INNER_W} y2={PAD.top + INNER_H}
                      stroke="oklch(40% 0 0)" stroke-width="1"
                    />

                    <!-- Legend -->
                    {#each rc.rLines as s, i}
                      <g transform="translate({PAD.left + i * 100}, 6)">
                        <line x1="0" y1="6" x2="18" y2="6" stroke={s.color} stroke-width="1.5"/>
                        <text x="22" y="10" font-size="10" fill="oklch(40% 0 0)" font-family="ui-monospace, monospace">
                          {s.name}
                        </text>
                      </g>
                    {/each}
                  </svg>
                </div>
              {/if}
            {:else}
              <div class="border border-base-300 rounded-lg p-4 text-center text-base-content/40 text-sm">
                Result data is present but could not be charted (empty time series).
              </div>
            {/if}
          </section>
        {:else}
          <div class="border border-dashed border-base-300 rounded-lg p-6 text-center text-base-content/40 text-sm">
            No results yet. Set a time range and run the simulation.
          </div>
        {/if}

        <!-- Delete study -->
        <div class="border-t border-base-300 pt-4">
          {#if confirmDelete}
            <p class="text-sm text-error mb-2">
              Delete "{$activeStudy.name}"? This cannot be undone.
            </p>
            <div class="flex gap-2">
              <button
                class="btn btn-error btn-sm"
                onclick={handleDelete}
                disabled={panelLoading}
              >
                {#if panelLoading}
                  <span class="loading loading-spinner loading-xs"></span>
                {/if}
                Confirm delete
              </button>
              <button
                class="btn btn-ghost btn-sm"
                onclick={() => { confirmDelete = false; }}
                disabled={panelLoading}
              >
                Cancel
              </button>
            </div>
          {:else}
            <button
              class="btn btn-ghost btn-sm text-error"
              onclick={handleDelete}
              disabled={panelLoading}
            >
              Delete study
            </button>
          {/if}
        </div>

      </div>
    {/if}

  </div>
</div>
