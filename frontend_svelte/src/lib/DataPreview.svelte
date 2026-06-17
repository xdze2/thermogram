<script>
  import { onMount, onDestroy } from 'svelte';
  import { dataSources, DATA_SOURCE_DEFS, rangeStart, rangeEnd, theme } from './store.js';

  let chartDiv;
  let status = '';
  let Plotly = null;
  let debounce = null;

  const TRACE_COLORS = { T_int: '#60a5fa', T_ext: '#34d399', Q_sol: '#fbbf24' };
  const TEMP_KEYS = ['T_int', 'T_ext'];
  const SOL_KEYS  = ['Q_sol'];

  onMount(async () => {
    // Plotly loaded via CDN script tag in index.html
    Plotly = window.Plotly;
    fetchPreview();
  });

  onDestroy(() => {
    if (Plotly && chartDiv) Plotly.purge(chartDiv);
  });

  // React to store changes
  const unsub1 = dataSources.subscribe(() => schedulePreview());
  const unsub2 = rangeStart.subscribe(() => schedulePreview());
  const unsub3 = rangeEnd.subscribe(() => schedulePreview());
  const unsub4 = theme.subscribe(() => schedulePreview());
  onDestroy(() => { unsub1(); unsub2(); unsub3(); unsub4(); });

  export function schedulePreview() {
    clearTimeout(debounce);
    debounce = setTimeout(fetchPreview, 300);
  }

  async function fetchPreview() {
    if (!Plotly) return;

    const ds = $dataSources;
    const selected = DATA_SOURCE_DEFS
      .map(d => ({ key: d.key, signal: ds[d.key] }))
      .filter(d => d.signal);

    if (!selected.length) {
      status = 'no signals selected';
      Plotly.purge(chartDiv);
      return;
    }

    const start = $rangeStart;
    const end   = $rangeEnd;
    const isoRe = /^\d{4}-\d{2}-\d{2}$/;
    if (!isoRe.test(start) || !isoRe.test(end)) {
      status = 'set start and end date (YYYY-MM-DD)';
      return;
    }

    status = 'loading…';
    const params = new URLSearchParams({ start: `${start}T00:00:00Z`, end: `${end}T23:59:59Z` });
    selected.forEach(d => params.append('signals', d.signal));

    let data;
    try {
      const r = await fetch(`/api/data?${params}`);
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      data = await r.json();
    } catch (e) {
      status = `error: ${e.message}`;
      return;
    }

    const isDark = $theme === 'dark';
    const paperBg = isDark ? '#1d232a' : '#ffffff';
    const plotBg  = isDark ? '#191e24' : '#f9fafb';
    const gridCol = isDark ? '#2a323c' : '#e5e7eb';
    const textCol = isDark ? '#a6adba' : '#374151';

    const tempSel = selected.filter(d => TEMP_KEYS.includes(d.key));
    const solSel  = selected.filter(d => SOL_KEYS.includes(d.key));
    const hasSol  = solSel.length > 0;

    const traces = [];
    tempSel.forEach(({ key, signal }) => {
      const pairs = data[signal] ?? [];
      traces.push({
        type: 'scatter', mode: 'lines', name: key,
        x: pairs.map(p => p[0]), y: pairs.map(p => p[1]),
        connectgaps: false,
        line: { color: TRACE_COLORS[key], width: 1.5 },
        xaxis: 'x', yaxis: 'y',
      });
    });
    solSel.forEach(({ key, signal }) => {
      const pairs = data[signal] ?? [];
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
      grid: hasSol ? { rows: 2, columns: 1, pattern: 'independent', roworder: 'top to bottom', rowheights: rowHeights } : undefined,
      xaxis:  { type: 'date', color: textCol, gridcolor: gridCol, tickfont: { size: 9 }, showticklabels: !hasSol },
      yaxis:  { color: textCol, gridcolor: gridCol, tickfont: { size: 9 }, zeroline: false, title: { text: '°C', font: { size: 9 } } },
      xaxis2: hasSol ? { type: 'date', color: textCol, gridcolor: gridCol, tickfont: { size: 9 } } : undefined,
      yaxis2: hasSol ? { color: textCol, gridcolor: gridCol, tickfont: { size: 9 }, zeroline: true, zerolinecolor: gridCol, title: { text: 'W/m²', font: { size: 9 } } } : undefined,
    };

    chartDiv.style.height = hasSol ? '340px' : '220px';
    Plotly.react(chartDiv, traces, layout, { responsive: true, displayModeBar: false });

    const totalPts = Object.values(data).reduce((n, pairs) => n + pairs.length, 0);
    status = totalPts ? `${totalPts} points` : 'no data in range';
  }
</script>

<div>
  <p class="text-xs uppercase tracking-widest text-base-content/30 mb-2">Data preview</p>
  <div class="text-xs text-base-content/30 mb-1">{status}</div>
  <div bind:this={chartDiv} style="height:220px;width:100%"></div>
</div>
