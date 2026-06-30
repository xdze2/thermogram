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
  // Study list actions
  // ---------------------------------------------------------------------------

  async function handleNewStudy() {
    await withPanelLoading(() => addStudy(modelId));
  }

  function selectStudy(study) {
    activeStudy.set(study);
    // Reset local edit state when switching studies
    editName = study.name;
    editStart = study.time_range?.start ? isoToDateStr(study.time_range.start) : '';
    editEnd   = study.time_range?.end   ? isoToDateStr(study.time_range.end)   : '';
    editResample = study.time_range?.resample ?? '15min';
    confirmDelete = false;
  }

  // ---------------------------------------------------------------------------
  // Reactive: keep local edit fields in sync when activeStudy changes from
  // outside (e.g. loadStudies re-populates the store after a run).
  // ---------------------------------------------------------------------------

  let editName     = '';
  let editStart    = '';
  let editEnd      = '';
  let editResample = '15min';
  let confirmDelete = false;

  $: if ($activeStudy) {
    editName     = $activeStudy.name;
    editStart    = $activeStudy.time_range?.start ? isoToDateStr($activeStudy.time_range.start) : '';
    editEnd      = $activeStudy.time_range?.end   ? isoToDateStr($activeStudy.time_range.end)   : '';
    editResample = $activeStudy.time_range?.resample ?? '15min';
  }

  // ---------------------------------------------------------------------------
  // Date helpers (shared with SimulationPanel approach)
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
    if (!editStart || !editEnd) return;
    const time_range = {
      start:    dateToUTCIso(editStart),
      end:      dateToUTCIso(editEnd),
      resample: editResample,
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

  $: chartData = computeChartData($activeStudy?.results?.simulate ?? null);

  function computeChartData(result) {
    if (!result?.t?.length) return null;

    const t     = result.t;
    const names = Object.keys(result.states);
    const allValues = names.flatMap(n => result.states[n]);

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

    return { series, yTicks, xTicks };
  }
</script>

<div class="p-4 space-y-4">

  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold">Studies</h2>
    <button
      class="btn btn-primary btn-sm"
      onclick={handleNewStudy}
      disabled={panelLoading}
    >
      {#if panelLoading && !$activeStudy}
        <span class="loading loading-spinner loading-xs"></span>
      {/if}
      + New study
    </button>
  </div>

  <!-- Panel-level error (create / patch / delete / clear-results errors) -->
  {#if panelError}
    <div role="alert" class="alert alert-error text-sm py-2">
      <span>{panelError}</span>
    </div>
  {/if}

  {#if $studies.length === 0}
    <div class="border border-base-300 rounded-lg p-8 text-center text-base-content/40 text-sm">
      No studies yet. Click "+ New study" to create one.
    </div>

  {:else}

    <!-- ================================================================
         Two-column layout: study list (left) + detail (right)
         On small screens: stacks vertically.
    ================================================================ -->
    <div class="grid grid-cols-1 md:grid-cols-[16rem_1fr] gap-4 items-start">

      <!-- ---- Study list ---- -->
      <div class="border border-base-300 rounded-lg overflow-hidden">
        <ul class="menu menu-compact p-0" role="listbox" aria-label="Studies list">
          {#each $studies as study (study.uid)}
            <li>
              <button
                class="flex flex-col items-start gap-0 px-3 py-2 w-full text-left rounded-none
                  {$activeStudy?.uid === study.uid ? 'active' : ''}"
                role="option"
                aria-selected={$activeStudy?.uid === study.uid}
                onclick={() => selectStudy(study)}
              >
                <span class="font-medium text-sm leading-snug truncate w-full">{study.name}</span>
                <span class="text-xs text-base-content/50">{formatDate(study.created_at)}</span>
                {#if study.results?.simulate}
                  <span class="badge badge-success badge-xs mt-0.5">results</span>
                {/if}
              </button>
            </li>
          {/each}
        </ul>
      </div>

      <!-- ---- Study detail ---- -->
      {#if $activeStudy}
        <div class="space-y-5">

          <!-- Name field -->
          <div class="form-control">
            <label class="label pb-1" for="study-name">
              <span class="label-text font-medium">Study name</span>
            </label>
            <input
              id="study-name"
              type="text"
              class="input input-bordered input-sm"
              bind:value={editName}
              onblur={saveName}
              onkeydown={handleNameKeydown}
              disabled={panelLoading}
              aria-label="Study name"
            />
          </div>

          <!-- Time range -->
          <fieldset class="border border-base-300 rounded-lg p-3 space-y-3">
            <legend class="px-1 text-sm font-medium">Time range</legend>

            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div class="form-control">
                <label class="label pb-0.5" for="study-start">
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

              <div class="form-control">
                <label class="label pb-0.5" for="study-end">
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

            <div class="form-control max-w-[12rem]">
              <label class="label pb-0.5" for="study-resample">
                <span class="label-text text-xs">Resample interval</span>
              </label>
              <select
                id="study-resample"
                class="select select-bordered select-sm"
                bind:value={editResample}
                onchange={saveTimeRange}
                disabled={panelLoading}
              >
                <option value="1min">1 min</option>
                <option value="5min">5 min</option>
                <option value="15min">15 min (default)</option>
                <option value="30min">30 min</option>
                <option value="1h">1 hour</option>
              </select>
            </div>

            {#if !editStart || !editEnd}
              <p class="text-xs text-warning">
                Set start and end dates before running the simulation.
              </p>
            {/if}
          </fieldset>

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
                  {editStart} → {editEnd} ({editResample})
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
                  </svg>
                </div>
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
      {:else}
        <!-- No active study selected -->
        <div class="border border-base-300 rounded-lg p-8 text-center text-base-content/40 text-sm">
          Select a study from the list to view or edit it.
        </div>
      {/if}

    </div>
  {/if}

</div>
