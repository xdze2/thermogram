<script>
  import { onMount, onDestroy } from "svelte";
  import { theme } from "./store.js";

  // input_data: dict signal_name → [[iso_ts, value], ...]
  export let inputData = null;
  // dataSources: { T_int, T_ext, GHI, direct, diffuse } → signal names
  export let dataSources = {};

  let chartDiv;
  let status = "";
  let Plotly = null;

  /** @type {Record<string, {color: string, width: number, opacity: number}>} */
  const TRACE_STYLES = {
    T_int: { color: "#60a5fa", width: 2, opacity: 1 },
    T_ext: { color: "#ef4444", width: 3, opacity: 0.6 },
    GHI: { color: "#fbbf24", width: 1, opacity: 1 },
    direct: { color: "#f97316", width: 1, opacity: 1 },
    diffuse: { color: "#a78bfa", width: 1, opacity: 1 },
  };
  // Palette for per-orientation G_i traces
  const G_COLORS = [
    "#fbbf24",
    "#f97316",
    "#f43f5e",
    "#a78bfa",
    "#34d399",
    "#60a5fa",
    "#94a3b8",
    "#e879f9",
  ];
  const TEMP_KEYS = ["T_int", "T_ext"];
  const RAW_SOL_KEYS = ["GHI", "direct", "diffuse"];

  const H_TEMP = 300; // temperature graph
  const H_SOL = 150; // solar irradiance graph
  const H_FIT = 400; // fit results (temperature) — phase 2
  const H_RESID = 250; // residuals — phase 2
  void H_FIT, H_RESID; // reserved for phase 2 subplots

  onMount(async () => {
    Plotly = window.Plotly;
    render();
  });

  onDestroy(() => {
    if (Plotly && chartDiv) Plotly.purge(chartDiv);
  });

  const unsubTheme = theme.subscribe(() => {
    if (Plotly) render();
  });
  onDestroy(unsubTheme);

  // Re-render whenever inputData or dataSources change
  $: if (Plotly && (inputData || dataSources)) render();

  function render() {
    if (!Plotly || !chartDiv) return;

    if (!inputData) {
      status = 'no cached data — click "Fetch data"';
      Plotly.purge(chartDiv);
      return;
    }

    const isDark = $theme === "dark";
    const paperBg = isDark ? "#1d232a" : "#ffffff";
    const plotBg = isDark ? "#191e24" : "#f9fafb";
    const gridCol = isDark ? "#2a323c" : "#e5e7eb";
    const textCol = isDark ? "#a6adba" : "#374151";

    const tempSel = TEMP_KEYS.map((k) => ({
      key: k,
      signal: dataSources[k],
    })).filter((d) => d.signal && inputData[d.signal]);

    // Raw irradiance signals (GHI / direct / diffuse) from InfluxDB
    const rawSolSel = RAW_SOL_KEYS.map((k) => ({
      key: k,
      signal: dataSources[k],
    })).filter((d) => d.signal && inputData[d.signal]);

    // Per-orientation POA irradiance keys computed by pvlib (G_S, G_E, …)
    const gOrientKeys = Object.keys(inputData)
      .filter((k) => k.startsWith("G_"))
      .sort();

    const hasSol = rawSolSel.length > 0 || gOrientKeys.length > 0;

    const traces = /** @type {object[]} */ ([]);

    // GHI background: full-height rectangles with opacity ∝ irradiance
    const ds = /** @type {Record<string, string>} */ (dataSources);
    const ghiKey = ds["GHI"];
    const ghiPairs = /** @type {[string, number][]|null} */ (
      ghiKey ? (inputData[ghiKey] ?? null) : null
    );
    const ghiShapes = [];
    if (ghiPairs && ghiPairs.length > 1) {
      const ghiMax = Math.max(...ghiPairs.map((p) => p[1]));
      for (let i = 0; i < ghiPairs.length; i++) {
        const val = ghiPairs[i][1];
        if (val <= 0) continue;
        const opacity = Math.min(val / ghiMax, 1) * 0.35;
        // bar width: half-step on each side
        const tMs = new Date(ghiPairs[i][0]).getTime();
        const prevMs =
          i > 0 ? new Date(ghiPairs[i - 1][0]).getTime() : tMs;
        const nextMs =
          i < ghiPairs.length - 1
            ? new Date(ghiPairs[i + 1][0]).getTime()
            : tMs;
        const halfStep = (nextMs - prevMs) / 4; // half of avg neighbour spacing
        const x0 = new Date(tMs - halfStep).toISOString();
        const x1 = new Date(tMs + halfStep).toISOString();
        ghiShapes.push({
          type: "rect",
          xref: "x",
          yref: "y domain",
          x0,
          x1,
          y0: 0,
          y1: 1,
          fillcolor: `rgba(251,191,36,${opacity.toFixed(3)})`,
          line: { width: 0 },
          layer: "below",
        });
      }
    }

    tempSel.forEach(({ key, signal }) => {
      const pairs = inputData[signal] ?? [];
      const s = TRACE_STYLES[key] ?? TRACE_STYLES.T_int;
      traces.push({
        type: "scatter",
        mode: "lines",
        name: key,
        x: pairs.map((p) => p[0]),
        y: pairs.map((p) => p[1]),
        connectgaps: false,
        line: { color: s.color, width: s.width },
        opacity: s.opacity,
        xaxis: "x",
        yaxis: "y",
      });
    });

    // Raw irradiance as thin dashed lines (context only)
    rawSolSel.forEach(({ key, signal }) => {
      const pairs = inputData[signal] ?? [];
      const { color } = TRACE_STYLES[key] ?? TRACE_STYLES.GHI;
      traces.push({
        type: "scatter",
        mode: "lines",
        name: key,
        x: pairs.map((p) => p[0]),
        y: pairs.map((p) => p[1]),
        connectgaps: false,
        line: { color, width: 1, dash: "dot" },
        xaxis: "x2",
        yaxis: "y2",
      });
    });

    // Per-orientation G_i as filled area traces
    gOrientKeys.forEach((key, i) => {
      const pairs = inputData[key] ?? [];
      const color = G_COLORS[i % G_COLORS.length];
      const orient = key.slice(2); // strip "G_"
      traces.push({
        type: "scatter",
        mode: "lines",
        name: `G_${orient}`,
        x: pairs.map((p) => p[0]),
        y: pairs.map((p) => p[1]),
        connectgaps: false,
        fill: "tozeroy",
        line: { color, width: 1.5 },
        fillcolor: color + "22",
        xaxis: "x2",
        yaxis: "y2",
      });
    });

    const legendH = 40; // px reserved at bottom for horizontal legend
    const gap = 20; // px gap between subplots
    const totalHeight = H_TEMP + (hasSol ? H_SOL + gap : 0) + legendH;

    // Convert pixel heights to [0,1] domain fractions (bottom-up in Plotly)
    const solBottom = legendH / totalHeight;
    const solTop = (legendH + (hasSol ? H_SOL : 0)) / totalHeight;
    const tempBottom = hasSol
      ? (legendH + H_SOL + gap) / totalHeight
      : legendH / totalHeight;
    const tempTop = 1;

    const layout = {
      height: totalHeight,
      paper_bgcolor: paperBg,
      plot_bgcolor: plotBg,
      margin: { t: 8, r: 10, b: 0, l: 45 },
      legend: {
        font: { size: 10, color: textCol },
        bgcolor: "transparent",
        orientation: "h",
        y: solBottom - 0.01,
        yanchor: "top",
      },
      font: { family: "ui-monospace, monospace", color: textCol },
      xaxis: {
        type: "date",
        color: textCol,
        gridcolor: gridCol,
        tickfont: { size: 9 },
        showticklabels: !hasSol,
        domain: [0, 1],
        anchor: "y",
      },
      yaxis: {
        color: textCol,
        gridcolor: gridCol,
        tickfont: { size: 9 },
        zeroline: false,
        title: { text: "°C", font: { size: 9 } },
        domain: [tempBottom, tempTop],
      },
      shapes: ghiShapes,
      ...(hasSol && {
        xaxis2: {
          type: "date",
          color: textCol,
          gridcolor: gridCol,
          tickfont: { size: 9 },
          domain: [0, 1],
          anchor: "y2",
        },
        yaxis2: {
          color: textCol,
          gridcolor: gridCol,
          tickfont: { size: 9 },
          zeroline: true,
          zerolinecolor: gridCol,
          title: { text: "W/m²", font: { size: 9 } },
          domain: [solBottom, solTop],
        },
      }),
    };

    const totalPts = Object.values(inputData).reduce(
      (n, pairs) => n + pairs.length,
      0,
    );
    if (!totalPts || traces.length === 0) {
      status = "no data to display";
      Plotly.purge(chartDiv);
      return;
    }

    Plotly.react(chartDiv, traces, layout, { displayModeBar: false });
    const firstPair = Object.values(inputData).find((p) => p.length)?.[0];
    const lastPair = Object.values(inputData)
      .find((p) => p.length)
      ?.at(-1);
    status = `${totalPts} pts · ${firstPair?.[0]?.slice(0, 10)} → ${lastPair?.[0]?.slice(0, 10)}`;
  }
</script>

<div>
  <p class="text-xs uppercase tracking-widest text-base-content/30 mb-2">
    Data preview
  </p>
  <div class="text-xs text-base-content/30 mb-1">{status}</div>
  <div bind:this={chartDiv} style="width:100%"></div>
</div>
