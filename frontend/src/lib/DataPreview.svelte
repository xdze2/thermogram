<script>
  import { onMount, onDestroy } from 'svelte';
  import { theme } from './store.js';

  // input_data: dict signal_name → [[iso_ts, value], ...]
  export let inputData = null;
  // dataSources: { T_int, T_ext, Q_sol } → signal names
  export let dataSources = {};

  let chartDiv;
  let status = '';
  let Plotly = null;

  const TRACE_COLORS = { T_int: '#60a5fa', T_ext: '#34d399', Q_sol: '#fbbf24' };
  const TEMP_KEYS = ['T_int', 'T_ext'];
  const SOL_KEYS  = ['Q_sol'];

  onMount(async () => {
    Plotly = window.Plotly;
    render();
  });

  onDestroy(() => {
    if (Plotly && chartDiv) Plotly.purge(chartDiv);
  });

  const unsubTheme = theme.subscribe(() => { if (Plotly) render(); });
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

    const isDark = $theme === 'dark';
    const paperBg = isDark ? '#1d232a' : '#ffffff';
    const plotBg  = isDark ? '#191e24' : '#f9fafb';
    const gridCol = isDark ? '#2a323c' : '#e5e7eb';
    const textCol = isDark ? '#a6adba' : '#374151';

    const tempSel = TEMP_KEYS
      .map(k => ({ key: k, signal: dataSources[k] }))
      .filter(d => d.signal && inputData[d.signal]);
    const solSel = SOL_KEYS
      .map(k => ({ key: k, signal: dataSources[k] }))
      .filter(d => d.signal && inputData[d.signal]);
    const hasSol = solSel.length > 0;

    const traces = [];
    tempSel.forEach(({ key, signal }) => {
      const pairs = inputData[signal] ?? [];
      traces.push({
        type: 'scatter', mode: 'lines', name: key,
        x: pairs.map(p => p[0]), y: pairs.map(p => p[1]),
        connectgaps: false,
        line: { color: TRACE_COLORS[key], width: 1.5 },
        xaxis: 'x', yaxis: 'y',
      });
    });
    solSel.forEach(({ key, signal }) => {
      const pairs = inputData[signal] ?? [];
      const color = TRACE_COLORS[key];
      traces.push({
        type: 'scatter', mode: 'lines', name: key,
        x: pairs.map(p => p[0]), y: pairs.map(p => p[1]),
        connectgaps: false,
        fill: 'tozeroy',
        line: { color, width: 1 },
        fillcolor: color + '33',
        xaxis: 'x2', yaxis: 'y2',
      });
    });

    const rowHeights = hasSol ? [0.6, 0.4] : [1];
    const layout = {
      paper_bgcolor: paperBg,
      plot_bgcolor:  plotBg,
      margin: { t: 8, r: 10, b: 36, l: 45 },
      legend: { font: { size: 10, color: textCol }, bgcolor: 'transparent', orientation: 'h', y: -0.12 },
      font: { family: 'ui-monospace, monospace', color: textCol },
      xaxis:  { type: 'date', color: textCol, gridcolor: gridCol, tickfont: { size: 9 }, showticklabels: !hasSol },
      yaxis:  { color: textCol, gridcolor: gridCol, tickfont: { size: 9 }, zeroline: false, title: { text: '°C', font: { size: 9 } } },
      ...(hasSol && {
        grid:   { rows: 2, columns: 1, pattern: 'independent', roworder: 'top to bottom', rowheights: rowHeights },
        xaxis2: { type: 'date', color: textCol, gridcolor: gridCol, tickfont: { size: 9 } },
        yaxis2: { color: textCol, gridcolor: gridCol, tickfont: { size: 9 }, zeroline: true, zerolinecolor: gridCol, title: { text: 'W/m²', font: { size: 9 } } },
      }),
    };

    const totalPts = Object.values(inputData).reduce((n, pairs) => n + pairs.length, 0);
    if (!totalPts || traces.length === 0) {
      status = 'no data to display';
      Plotly.purge(chartDiv);
      return;
    }

    chartDiv.style.height = hasSol ? '340px' : '220px';
    Plotly.react(chartDiv, traces, layout, { responsive: true, displayModeBar: false });
    const firstPair = Object.values(inputData).find(p => p.length)?.[0];
    const lastPair  = Object.values(inputData).find(p => p.length)?.at(-1);
    status = `${totalPts} pts · ${firstPair?.[0]?.slice(0, 10)} → ${lastPair?.[0]?.slice(0, 10)}`;
  }
</script>

<div>
  <p class="text-xs uppercase tracking-widest text-base-content/30 mb-2">Data preview</p>
  <div class="text-xs text-base-content/30 mb-1">{status}</div>
  <div bind:this={chartDiv} style="height:220px;width:100%"></div>
</div>
