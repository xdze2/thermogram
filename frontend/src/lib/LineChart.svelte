<script>
  /**
   * LineChart — thin uPlot wrapper for time-series data.
   *
   * Props:
   *   data      uPlot data array: [xValues, ...ySeries]. Each entry is a
   *             Float64Array or plain number[]; null entries produce gaps.
   *   series    Array of { label, stroke, width?, dash? } — one per Y series
   *             (same order as data[1..]). `dash` is a uPlot dash array e.g. [4,3].
   *   xLabel    X-axis title string.
   *   yLabel    Y-axis title string.
   *   height    Chart height in px (default 200). Width fills the container.
   *   refLine   Optional Y value for a dashed horizontal reference line (e.g. 0
   *             for the residuals zero-line). Omit or pass null to draw nothing.
   *   ariaLabel Accessible label for the chart wrapper div.
   */
  import { onMount, onDestroy } from 'svelte';
  import uPlot from 'uplot';
  import 'uplot/dist/uPlot.min.css';

  // ---------------------------------------------------------------------------
  // Props
  // ---------------------------------------------------------------------------

  /** @type {(number[] | null)[] | null} */
  export let data   = null;

  /** @type {{ label: string, stroke: string, width?: number, dash?: number[] }[]} */
  export let series = [];

  export let xLabel    = '';
  export let yLabel    = '';
  export let height    = 200;
  export let refLine   = null;
  export let ariaLabel = 'Line chart';

  // ---------------------------------------------------------------------------
  // Internal state
  // ---------------------------------------------------------------------------

  /** @type {HTMLDivElement | null} */
  let container = null;

  /** @type {uPlot | null} */
  let chart = null;

  /** Tracks the series identity we last built the chart with. */
  let builtSeriesKey = '';

  /** Tracks the refLine value we last built the chart with. */
  let builtRefLine;

  // ---------------------------------------------------------------------------
  // UTC tick formatter — renders as "DD/MM HHh" in UTC, matching the previous
  // hand-rolled SVG labels.
  // ---------------------------------------------------------------------------

  /** @param {number} ts  Unix timestamp in seconds */
  function fmtTick(ts) {
    const d  = new Date(ts * 1000);
    const dd = String(d.getUTCDate()).padStart(2, '0');
    const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
    const hh = String(d.getUTCHours()).padStart(2, '0');
    return `${dd}/${mm} ${hh}h`;
  }

  // ---------------------------------------------------------------------------
  // Reference-line plugin (draws a dashed horizontal line at refLine Y value)
  // ---------------------------------------------------------------------------

  function makeRefLinePlugin(yVal) {
    return {
      hooks: {
        draw: [
          (u) => {
            const { ctx, bbox } = u;
            const yPx = u.valToPos(yVal, 'y', true);
            if (yPx < bbox.top || yPx > bbox.top + bbox.height) return;
            ctx.save();
            ctx.beginPath();
            ctx.setLineDash([4, 3]);
            ctx.strokeStyle = 'oklch(50% 0 0)';
            ctx.lineWidth   = 1;
            ctx.moveTo(bbox.left, yPx);
            ctx.lineTo(bbox.left + bbox.width, yPx);
            ctx.stroke();
            ctx.restore();
          },
        ],
      },
    };
  }

  // ---------------------------------------------------------------------------
  // Build the uPlot options object from current props
  // ---------------------------------------------------------------------------

  function buildOpts(w) {
    /** @type {uPlot.Series[]} */
    const uSeries = [
      // X series (time) — uPlot always expects one as first entry
      {
        value: (u, v) => (v != null ? fmtTick(v) : '--'),
      },
      // Y series
      ...series.map((s) => ({
        label:  s.label,
        stroke: s.stroke,
        width:  s.width ?? 2,
        dash:   s.dash ?? [],
        points: { show: false },
        spanGaps: false,
      })),
    ];

    const plugins = [];
    if (refLine != null) {
      plugins.push(makeRefLinePlugin(refLine));
    }

    return {
      width:  w,
      height: height,
      plugins,
      series: uSeries,
      axes: [
        // X axis — UTC formatted
        {
          label:  xLabel,
          // uPlot's default time axis uses local time; override values formatter
          // to produce UTC labels. We also disable uPlot's built-in time-zone
          // conversion by supplying a custom `values` function.
          values: (u, splits) => splits.map((v) => fmtTick(v)),
          space:  60,
        },
        // Y axis
        {
          label: yLabel,
          size:  50,
        },
      ],
      scales: {
        // Tell uPlot that X is time (seconds since epoch, UTC).
        x: { time: true },
      },
      // Suppress uPlot's internal locale-time conversion so our UTC formatter
      // is authoritative.
      tzDate: (ts) => uPlot.tzDate(new Date(ts * 1e3), 'UTC'),
    };
  }

  // ---------------------------------------------------------------------------
  // Mount / destroy lifecycle
  // ---------------------------------------------------------------------------

  function createChart() {
    if (!container || !data) return;
    if (chart) {
      chart.destroy();
      chart = null;
    }
    const w    = container.clientWidth || 400;
    const opts = buildOpts(w);
    chart = new uPlot(opts, data, container);
    builtSeriesKey = seriesKey;
    builtRefLine   = refLine;
  }

  onMount(() => {
    // Chart creation is driven by the reactive block below (it fires once
    // `data` and `container` are both ready). Here we only wire up resizing.

    // ResizeObserver — keeps chart width in sync with the container.
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = entry.contentRect.width;
        if (chart && w > 0) {
          chart.setSize({ width: w, height });
        }
      }
    });
    if (container) ro.observe(container);

    return () => {
      ro.disconnect();
    };
  });

  onDestroy(() => {
    chart?.destroy();
    chart = null;
  });

  // ---------------------------------------------------------------------------
  // Reactive updates
  // ---------------------------------------------------------------------------

  // Recompute a stable key for the series config so we know when it changed.
  $: seriesKey = JSON.stringify(series.map((s) => s.label + s.stroke + (s.dash ?? [])));

  // Single reactive driver for prop changes. The branches compare against the
  // values stamped by createChart(), so after a rebuild the rebuild conditions
  // are false — this block does NOT loop on its own reassignment of `chart`.
  // The series config and refLine are baked into the uPlot options, so changing
  // either requires a full rebuild; a data-only change uses the cheap setData.
  $: if (data && container) {
    if (!chart || seriesKey !== builtSeriesKey || refLine !== builtRefLine) {
      createChart();
    } else {
      chart.setData(data);
    }
  }
</script>

<!-- role="img" wrapper gives screen readers a handle for the chart area. -->
<div
  bind:this={container}
  role="img"
  aria-label={ariaLabel}
  style="width: 100%;"
></div>
