<script>
  import { assembly, loading, error } from '../stores/model.js';
  import { runSimulate, fetchIdentifiability } from '../lib/api.js';

  // ---------------------------------------------------------------------------
  // Identifiability
  // ---------------------------------------------------------------------------
  let identStatus = null;     // { param_status: { name: {status, reason, tau_h, correlation} } }
  let identLoading = false;
  let identError   = '';

  async function loadIdentifiability() {
    identLoading = true;
    identError   = '';
    try {
      identStatus = await fetchIdentifiability();
    } catch (err) {
      identError = err.message ?? String(err);
    } finally {
      identLoading = false;
    }
  }

  const STATUS_BADGE = {
    resolvable:      'badge-success',
    borderline:      'badge-warning',
    prior_dominated: 'badge-error',
  };

  function statusBadge(s) {
    return STATUS_BADGE[s] ?? 'badge-ghost';
  }

  // ---------------------------------------------------------------------------
  // Simulation
  // ---------------------------------------------------------------------------
  let simResult = null;
  let simLoading = false;
  let simError   = '';

  // Scenario inputs — sliders for quick iteration
  let tExtOffset = 0;     // °C offset added to a synthetic T_ext base
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
    try {
      const signals = buildScenario(tExtOffset, solarIntensity);
      const states  = $assembly?.states ?? ['T_room'];
      const x0 = states.map(() => 18.0);  // start all states at 18°C
      simResult = await runSimulate(signals, x0);
    } catch (err) {
      simError = err.message ?? String(err);
    } finally {
      simLoading = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Hand-rolled SVG line chart
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

    // X-axis ticks (hours)
    const nXTicks = 6;
    const xTicks = Array.from({ length: nXTicks + 1 }, (_, i) => {
      const tv = tMin + i * (tMax - tMin) / nXTicks;
      return { label: `${Math.round(tv / 3600)}h`, x: scaleX(tv) };
    });

    return { series, yTicks, xTicks, vMin: (vMin - vPad).toFixed(1), vMax: (vMax + vPad).toFixed(1) };
  }
</script>

<div class="p-4 space-y-6">

  <!-- =========================================================
       Identifiability report
       (Per-parameter priors now live inline on the module cards;
        this section is the detailed pre-fit verdict with τ/correlation.)
  ========================================================= -->
  <section>
    <h2 class="text-xl font-semibold mb-1">
      Identifiability
      <span class="badge badge-ghost badge-sm ml-2 align-middle">about fitting, not simulating</span>
    </h2>
    <p class="text-sm text-base-content/60 mb-3">
      Pre-fit verdict: predicts which parameters the observed signals can resolve,
      before running any Bayesian inference. Computed from the eigenstructure
      of the linearised system and the broadband signal statistics.
    </p>

    {#if identLoading}
      <div class="flex justify-center py-6">
        <span class="loading loading-spinner loading-md"></span>
      </div>
    {:else if identError}
      <div role="alert" class="alert alert-error mb-3">
        <span>{identError}</span>
      </div>
    {:else if identStatus}
      <div class="overflow-x-auto">
        <table class="table table-sm w-full">
          <thead>
            <tr>
              <th>Parameter</th>
              <th>Status</th>
              <th class="text-right">&tau; (h)</th>
              <th class="text-right">Max correlation</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {#each Object.entries(identStatus.param_status) as [name, info]}
              <tr class="hover">
                <td class="font-mono font-medium">{name}</td>
                <td>
                  <span class="badge {statusBadge(info.status)} badge-sm">
                    {info.status.replace('_', ' ')}
                  </span>
                </td>
                <td class="text-right font-mono">
                  {info.tau_h != null ? info.tau_h.toFixed(1) : '—'}
                </td>
                <td class="text-right font-mono">
                  {info.correlation != null ? info.correlation.toFixed(2) : '—'}
                </td>
                <td class="text-sm text-base-content/70">{info.reason}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {:else}
      <p class="text-base-content/60 text-sm">
        Run the identifiability check to see verdicts.
      </p>
    {/if}

    <button
      class="btn btn-outline btn-sm mt-3"
      onclick={loadIdentifiability}
      disabled={identLoading || !$assembly?.parameters?.length}
    >
      {identLoading ? 'Checking…' : 'Run identifiability check'}
    </button>
  </section>

  <!-- =========================================================
       Forward simulation
  ========================================================= -->
  <section>
    <h2 class="text-xl font-semibold mb-1">Forward simulation</h2>
    <p class="text-sm text-base-content/60 mb-3">
      Sends a synthetic 48-hour scenario to the server and plots the returned
      state trajectories. Adjust the sliders to explore different conditions.
    </p>

    <!-- Scenario sliders -->
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
      <div class="form-control">
        <label class="label" for="t-ext-offset">
          <span class="label-text">T_ext offset</span>
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
          <span class="label-text">Peak solar G_sol</span>
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

    <!-- Action buttons -->
    <div class="flex gap-2 flex-wrap mb-4">
      <button
        class="btn btn-primary btn-sm"
        onclick={runSim}
        disabled={simLoading || !$assembly}
      >
        {#if simLoading}
          <span class="loading loading-spinner loading-xs"></span>
        {/if}
        Run simulation
      </button>
    </div>

    {#if simError}
      <div role="alert" class="alert alert-error mb-3 text-sm">
        <span>{simError}</span>
      </div>
    {/if}

    <!-- SVG line chart -->
    {#if chartData}
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
          >Time (hours)</text>
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
        Press "Run simulation" to see the temperature trajectory.
      </div>
    {/if}
  </section>

</div>
