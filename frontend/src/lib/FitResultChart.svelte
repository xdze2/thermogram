<script>
  import { onMount, onDestroy } from 'svelte';
  import { theme } from './store.js';

  // fitResult: the dict returned by POST /fit
  export let fitResult = null;
  // T_obs: [[iso_ts, value], ...] from input_data for T_int signal
  export let tObsPairs = null;

  let chartDiv;
  let Plotly = null;

  onMount(async () => {
    Plotly = window.Plotly;
    render();
  });

  onDestroy(() => {
    if (Plotly && chartDiv) Plotly.purge(chartDiv);
  });

  const unsubTheme = theme.subscribe(() => { if (Plotly) render(); });
  onDestroy(unsubTheme);

  $: if (Plotly && fitResult) render();

  function render() {
    if (!Plotly || !chartDiv || !fitResult) return;

    const ts = fitResult.timestamps ?? [];
    const T_room_pred = fitResult.T_room_pred ?? [];
    const T_wall_pred = fitResult.T_wall_pred ?? [];

    if (!ts.length || !T_room_pred.length) {
      Plotly.purge(chartDiv);
      return;
    }

    // Build T_obs lookup aligned to fit timestamps
    const obsMap = {};
    if (tObsPairs) {
      for (const [t, v] of tObsPairs) obsMap[t] = v;
    }
    const T_obs_vals = ts.map(t => obsMap[t] ?? null);
    const residuals  = ts.map((t, i) => {
      const obs = obsMap[t];
      return (obs != null && T_room_pred[i] != null) ? obs - T_room_pred[i] : null;
    });

    const isDark = $theme === 'dark';
    const paperBg = isDark ? '#1d232a' : '#ffffff';
    const plotBg  = isDark ? '#191e24' : '#f9fafb';
    const gridCol = isDark ? '#2a323c' : '#e5e7eb';
    const textCol = isDark ? '#a6adba' : '#374151';
    const zeroCol = isDark ? '#3d4a5c' : '#d1d5db';

    const traces = [
      {
        name: 'T_obs',
        x: ts, y: T_obs_vals,
        type: 'scatter', mode: 'lines',
        line: { color: '#60a5fa', width: 1.5 },
        connectgaps: false,
        xaxis: 'x', yaxis: 'y',
      },
      {
        name: 'T_room (fit)',
        x: ts, y: T_room_pred,
        type: 'scatter', mode: 'lines',
        line: { color: '#f97316', width: 1.5 },
        xaxis: 'x', yaxis: 'y',
      },
      {
        name: 'T_wall (fit)',
        x: ts, y: T_wall_pred,
        type: 'scatter', mode: 'lines',
        line: { color: '#a78bfa', width: 1, dash: 'dot' },
        xaxis: 'x', yaxis: 'y',
      },
      {
        name: 'residual',
        x: ts, y: residuals,
        type: 'scatter', mode: 'lines',
        line: { color: '#94a3b8', width: 1 },
        fill: 'tozeroy',
        fillcolor: isDark ? '#94a3b820' : '#94a3b830',
        connectgaps: false,
        xaxis: 'x2', yaxis: 'y2',
      },
    ];

    const layout = {
      paper_bgcolor: paperBg,
      plot_bgcolor:  plotBg,
      margin: { t: 8, r: 10, b: 36, l: 48 },
      legend: {
        font: { size: 10, color: textCol },
        bgcolor: 'transparent',
        orientation: 'h', y: -0.12,
      },
      font: { family: 'ui-monospace, monospace', color: textCol },
      grid: { rows: 2, columns: 1, pattern: 'independent', roworder: 'top to bottom', rowheights: [0.65, 0.35] },
      xaxis:  { type: 'date', color: textCol, gridcolor: gridCol, tickfont: { size: 9 }, showticklabels: false },
      yaxis:  { color: textCol, gridcolor: gridCol, tickfont: { size: 9 }, zeroline: false, title: { text: '°C', font: { size: 9 } } },
      xaxis2: { type: 'date', color: textCol, gridcolor: gridCol, tickfont: { size: 9 } },
      yaxis2: {
        color: textCol, gridcolor: gridCol, tickfont: { size: 9 },
        zeroline: true, zerolinecolor: zeroCol,
        title: { text: 'ΔT °C', font: { size: 9 } },
      },
    };

    chartDiv.style.height = '380px';
    Plotly.react(chartDiv, traces, layout, { responsive: true, displayModeBar: false });
  }
</script>

<div bind:this={chartDiv} style="height:380px;width:100%"></div>
