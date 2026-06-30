<script>
  import { assembly, requiredSignals, loading, error } from '../stores/model.js';
  import { runSimulate, runSimulateBound } from './api.js';

  // ---------------------------------------------------------------------------
  // Shared simulation result state
  // Both the synthetic path and the bound path write here; one chart renders both.
  // ---------------------------------------------------------------------------
  let simResult = null;
  let simLoading = false;
  let simError   = '';
  /**
   * Which path produced the current result, so the legend is informative.
   * @type {'synthetic' | 'bound' | null}
   */
  let simSource = null;

  // ---------------------------------------------------------------------------
  // Path A: Synthetic scenario (sliders)
  // ---------------------------------------------------------------------------

  let tExtOffset = 0;       // °C offset added to a synthetic T_ext base
  let solarIntensity = 300; // W/m² peak solar for the synthetic G_sol

  /** Build a 48-hour synthetic signal pair at 1h resolution. */
  function buildScenario(tExtOffsetVal, solarPeak) {
    const n = 48;
    const T_ext = [];
    const G_sol = [];
    for (let i = 0; i < n; i++) {
      // Diurnal T_ext: base 10°C + 5°C daily swing, offset by slider
      const hour = i % 24;
      T_ext.push(10 + tExtOffsetVal + 5 * Math.sin((Math.PI / 12) * (hour - 6)));
      // Solar: trapezoid from hour 7–17
      if (hour >= 7 && hour <= 17) {
        G_sol.push(solarPeak * Math.sin(Math.PI * (hour - 7) / 10));
      } else {
        G_sol.push(0);
      }
    }
    return { T_ext, G_sol };
  }

  async function runSim() {
    simLoading = true;
    simError   = '';
    simResult  = null;
    simSource  = null;
    try {
      const signals = buildScenario(tExtOffset, solarIntensity);
      const states  = $assembly?.states ?? ['T_room'];
      const x0 = states.map(() => 18.0);  // start all states at 18°C
      simResult = await runSimulate(signals, x0);
      simSource = 'synthetic';
    } catch (err) {
      simError = err.message ?? String(err);
    } finally {
      simLoading = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Path B: Bound simulation (real InfluxDB data)
  // ---------------------------------------------------------------------------

  /** Return today as "YYYY-MM-DD" (UTC). */
  function todayUTCDate() {
    return new Date().toISOString().slice(0, 10);
  }

  /** Return the date N days ago as "YYYY-MM-DD" (UTC). */
  function daysAgoUTCDate(n) {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - n);
    return d.toISOString().slice(0, 10);
  }

  /** Convert a "YYYY-MM-DD" date string to a UTC midnight ISO-8601 string. */
  function dateToUTCIso(dateStr) {
    return `${dateStr}T00:00:00Z`;
  }

  let boundStartDate = daysAgoUTCDate(7);
  let boundEndDate   = todayUTCDate();
  let boundResample = '15min';

  /** All required signals have a non-null binding. */
  $: allBound = $requiredSignals.length > 0 && $requiredSignals.every(s => !!s.binding);

  async function runSimBound() {
    simLoading = true;
    simError   = '';
    simResult  = null;
    simSource  = null;
    try {
      simResult = await runSimulateBound(
        dateToUTCIso(boundStartDate),
        dateToUTCIso(boundEndDate),
        boundResample,
      );
      simSource = 'bound';
    } catch (err) {
      simError = err.message ?? String(err);
    } finally {
      simLoading = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Hand-rolled SVG line chart (shared by both paths)
  // ---------------------------------------------------------------------------

  const CHART_W = 560;
  const CHART_H = 200;
  const PAD = { top: 16, right: 16, bottom: 36, left: 44 };
  const INNER_W = CHART_W - PAD.left - PAD.right;
  const INNER_H = CHART_H - PAD.top  - PAD.bottom;

  const LINE_COLORS = ['oklch(55% 0.18 250)', 'oklch(60% 0.18 40)'];

  $: chartData = computeChartData(simResult);

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

    // X-axis ticks: for bound results use date labels; for synthetic use hours.
    let xTicks;
    const nXTicks = 6;
    if (simSource === 'bound') {
      // t is seconds from epoch; convert to date strings.
      xTicks = Array.from({ length: nXTicks + 1 }, (_, i) => {
        const tv = tMin + i * (tMax - tMin) / nXTicks;
        const d = new Date(tv * 1000);
        const label = `${String(d.getUTCDate()).padStart(2,'0')}/${String(d.getUTCMonth() + 1).padStart(2,'0')} ${String(d.getUTCHours()).padStart(2,'0')}h`;
        return { label, x: scaleX(tv) };
      });
    } else {
      xTicks = Array.from({ length: nXTicks + 1 }, (_, i) => {
        const tv = tMin + i * (tMax - tMin) / nXTicks;
        return { label: `${Math.round(tv / 3600)}h`, x: scaleX(tv) };
      });
    }

    return { series, yTicks, xTicks };
  }

  // X-axis label depends on which simulation source produced the result
  $: xAxisLabel = simSource === 'bound' ? 'Date/time' : 'Time (hours)';
</script>

<div class="p-4 space-y-6">

  <!-- =========================================================
       Forward simulation — Path A: Synthetic scenario
  ========================================================= -->
  <section>
    <h2 class="text-xl font-semibold mb-1">
      Synthetic simulation
      <span class="badge badge-ghost badge-sm ml-2 align-middle">quick exploration</span>
    </h2>
    <p class="text-sm text-base-content/60 mb-3">
      Sends a synthetic 48-hour scenario to the server and plots the returned
      state trajectories. Adjust the sliders to explore different conditions.
    </p>

    <!-- Scenario sliders (ad-hoc; cover the common T_ext + G_sol case) -->
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
      <div class="form-control">
        <label class="label" for="t-ext-offset">
          <span class="label-text">T_ext offset [°C]</span>
          <span class="label-text-alt font-mono">{tExtOffset >= 0 ? '+' : ''}{tExtOffset} °C</span>
        </label>
        <input
          id="t-ext-offset"
          type="range"
          min="-15"
          max="25"
          step="1"
          class="range range-primary"
          bind:value={tExtOffset}
        />
        <div class="flex justify-between text-xs text-base-content/50 px-1">
          <span>-15</span><span>+25 °C</span>
        </div>
      </div>

      <div class="form-control">
        <label class="label" for="solar-intensity">
          <span class="label-text">Peak solar G_sol [W/m²]</span>
          <span class="label-text-alt font-mono">{solarIntensity} W/m²</span>
        </label>
        <input
          id="solar-intensity"
          type="range"
          min="0"
          max="900"
          step="50"
          class="range range-secondary"
          bind:value={solarIntensity}
        />
        <div class="flex justify-between text-xs text-base-content/50 px-1">
          <span>0</span><span>900 W/m²</span>
        </div>
      </div>
    </div>

    <button
      class="btn btn-primary btn-sm"
      onclick={runSim}
      disabled={simLoading || !$assembly}
    >
      {#if simLoading && simSource === null}
        <span class="loading loading-spinner loading-xs"></span>
      {/if}
      Run simulation
    </button>
  </section>

  <!-- =========================================================
       Forward simulation — Path B: Bound (real InfluxDB data)
  ========================================================= -->
  <section>
    <h2 class="text-xl font-semibold mb-1">
      Real-data simulation
      <span class="badge badge-accent badge-sm ml-2 align-middle">InfluxDB</span>
    </h2>
    <p class="text-sm text-base-content/60 mb-3">
      Fetches real measurements from InfluxDB for the bound signals and runs the
      forward simulation. All required signals must be bound above.
    </p>

    {#if $requiredSignals.length > 0 && !allBound}
      <div role="alert" class="alert alert-warning mb-3 text-sm py-2">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
          <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
        </svg>
        <span>
          Bind all required signals above before running.
          Unbound:
          {$requiredSignals.filter(s => !s.binding).map(s => s.name).join(', ')}.
        </span>
      </div>
    {/if}

    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
      <div class="form-control">
        <label class="label" for="bound-start">
          <span class="label-text">Start (UTC)</span>
        </label>
        <input
          id="bound-start"
          type="date"
          class="input input-bordered input-sm"
          bind:value={boundStartDate}
        />
      </div>

      <div class="form-control">
        <label class="label" for="bound-end">
          <span class="label-text">End (UTC)</span>
        </label>
        <input
          id="bound-end"
          type="date"
          class="input input-bordered input-sm"
          bind:value={boundEndDate}
        />
      </div>
    </div>

    <div class="form-control mb-4 max-w-[12rem]">
      <label class="label" for="bound-resample">
        <span class="label-text">Resample interval</span>
      </label>
      <select id="bound-resample" class="select select-bordered select-sm" bind:value={boundResample}>
        <option value="1min">1 min</option>
        <option value="5min">5 min</option>
        <option value="15min">15 min (default)</option>
        <option value="30min">30 min</option>
        <option value="1h">1 hour</option>
      </select>
    </div>

    <button
      class="btn btn-accent btn-sm"
      onclick={runSimBound}
      disabled={simLoading || !$assembly || !allBound}
    >
      {#if simLoading && simSource === null}
        <span class="loading loading-spinner loading-xs"></span>
      {/if}
      Run with real data
    </button>
  </section>

  <!-- =========================================================
       Shared result area — used by BOTH simulation paths
  ========================================================= -->
  <section aria-label="Simulation results">

    {#if simLoading}
      <div class="flex justify-center py-6">
        <span class="loading loading-spinner loading-md"></span>
      </div>
    {/if}

    {#if simError}
      <div role="alert" class="alert alert-error mb-3 text-sm">
        <span>{simError}</span>
      </div>
    {/if}

    <!-- SVG line chart — shared by both paths -->
    {#if chartData}
      <!-- Source label so user knows which path produced the current chart -->
      <div class="flex items-center gap-2 mb-2">
        {#if simSource === 'bound'}
          <span class="badge badge-accent badge-sm">Real data — InfluxDB</span>
          <span class="text-xs text-base-content/60">
            {boundStartDate} → {boundEndDate} ({boundResample})
          </span>
        {:else}
          <span class="badge badge-ghost badge-sm">Synthetic scenario</span>
          <span class="text-xs text-base-content/60">48-hour synthetic signals</span>
        {/if}
      </div>

      <div class="border border-base-300 rounded-lg p-2 overflow-x-auto">
        <svg
          viewBox="0 0 {CHART_W} {CHART_H}"
          width="100%"
          style="max-width: {CHART_W}px;"
          role="img"
          aria-label="Simulated temperature trajectories over time"
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
          >{xAxisLabel}</text>
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
            <clipPath id="chart-clip">
              <rect x={PAD.left} y={PAD.top} width={INNER_W} height={INNER_H} />
            </clipPath>
          </defs>

          <!-- Series lines -->
          <g clip-path="url(#chart-clip)">
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
    {:else if !simLoading}
      <div class="border border-base-300 rounded-lg p-8 text-center text-base-content/40 text-sm">
        Press "Run simulation" or "Run with real data" to see the temperature trajectory.
      </div>
    {/if}

  </section>

</div>
