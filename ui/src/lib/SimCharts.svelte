<script>
	// Presentational chart block shared by forward-run and fit results.
	// Renders temperatures (sim + observed + boundary overlay), input power,
	// and residuals from a /simulate/run-shaped result.
	import { onDestroy } from 'svelte';
	import uPlot from 'uplot';
	import 'uplot/dist/uPlot.min.css';

	let {
		simResult   = null,   // { t, nodes, atomic_model, meta? }
		inputSeries = null,   // { node_id: { t, values, label } }
		obsSeries   = null,   // { node_id: { t, values, label } }
		showMeta    = true,
	} = $props();

	// ── node metadata derived from the fitted/forward atomic model ──────────────
	const rcNodes = $derived(simResult?.atomic_model?.nodes ?? []);
	const nodeKindMap = $derived(Object.fromEntries(rcNodes.map((n) => [n.id, n.kind])));
	const nodeLabels  = $derived(Object.fromEntries(rcNodes.map((n) => [n.id, n.label ?? n.id])));
	const nodeSolarIds = $derived(
		new Set(rcNodes.filter((n) => n.id.startsWith('solar_')).map((n) => n.id))
	);
	const nodeWallMassIds = $derived(
		new Set(rcNodes.filter((n) => n.kind === 'mass' && n.id.startsWith('m_')).map((n) => n.id))
	);

	const hasObs = $derived(obsSeries && Object.keys(obsSeries).length > 0);

	// ── uPlot helpers ───────────────────────────────────────────────────────────
	const SIM_COLORS = ['#38bdf8', '#fb923c', '#a78bfa', '#34d399', '#f472b6', '#facc15'];
	const OBS_COLORS = ['#fde68a', '#fca5a5', '#d9f99d', '#e9d5ff'];
	const INP_COLORS = ['#64748b', '#475569', '#94a3b8', '#6b7280', '#9ca3af'];

	const AXIS_STYLE   = { stroke: '#94a3b8', ticks: { stroke: '#334155' }, grid: { stroke: '#1e293b' } };
	const AXIS_Y       = { stroke: '#94a3b8', ticks: { stroke: '#334155' }, grid: { stroke: '#334155' }, label: '°C' };
	const AXIS_Y_RESID = { stroke: '#94a3b8', ticks: { stroke: '#334155' }, grid: { stroke: '#334155' }, label: 'Δ°C' };
	const SOLAR_STYLE  = { stroke: '#ca8a04', fill: 'rgba(234,179,8,0.18)', width: 1, spanGaps: false };

	function makeUplot(container, opts, data) {
		return new uPlot(opts, data, container);
	}

	function nearestIdx(sortedMs, tms) {
		if (sortedMs.length === 0) return -1;
		let lo = 0, hi = sortedMs.length - 1;
		while (lo < hi) {
			const mid = (lo + hi) >> 1;
			if (sortedMs[mid] < tms) lo = mid + 1; else hi = mid;
		}
		return lo;
	}

	// ── temperature chart ─────────────────────────────────────────────────────
	let tempContainer = $state(null);
	let tempChart     = null;

	function buildTempChart() {
		if (tempChart) { tempChart.destroy(); tempChart = null; }
		if (!tempContainer || !simResult) return;

		const ts      = simResult.t.map((s) => Date.parse(s) / 1000);
		const massIds = Object.keys(simResult.nodes);
		const simTsMs = simResult.t.map((s) => Date.parse(s));

		const simSeries = massIds.map((id, i) => ({
			label: nodeLabels[id] ?? id,
			stroke: SIM_COLORS[i % SIM_COLORS.length],
			width: 1.5, spanGaps: false,
			show: !nodeWallMassIds.has(id),
		}));
		const simData = massIds.map((id) => simResult.nodes[id].map((v) => (v === null ? NaN : v)));

		const obsIds = obsSeries ? Object.keys(obsSeries).filter((id) => simResult.nodes[id] !== undefined) : [];
		const obsSer = obsIds.map((id, i) => ({
			label: `${nodeLabels[id] ?? id} (obs)`,
			stroke: OBS_COLORS[i % OBS_COLORS.length],
			width: 1, dash: [4, 3], spanGaps: false,
		}));
		const obsData = obsIds.map((id) => {
			const obs   = obsSeries[id];
			const obsMs = obs.t.map((s) => Date.parse(s));
			return simTsMs.map((tms) => {
				const idx = nearestIdx(obsMs, tms);
				return idx >= 0 ? (obs.values[idx] ?? NaN) : NaN;
			});
		});

		const bndEntries = inputSeries
			? Object.entries(inputSeries).filter(([id]) => nodeKindMap[id] === 'boundary')
			: [];
		const bndSeries = bndEntries.map(([, e], i) => ({
			label: e.label, stroke: INP_COLORS[i % INP_COLORS.length], width: 1.5, spanGaps: false,
		}));
		const bndData = bndEntries.map(([, e]) => {
			const bndMs = e.t.map((s) => Date.parse(s));
			return simTsMs.map((tms) => {
				const idx = nearestIdx(bndMs, tms);
				return idx >= 0 ? (e.values[idx] ?? NaN) : NaN;
			});
		});

		const data   = [ts, ...simData, ...obsData, ...bndData];
		const series = [{}, ...simSeries, ...obsSer, ...bndSeries];

		tempChart = makeUplot(tempContainer, {
			width: tempContainer.clientWidth || 800, height: 260,
			cursor: { show: true }, scales: { x: { time: true } }, series,
			axes: [AXIS_STYLE, AXIS_Y],
			legend: { show: true },
		}, data);
	}

	// ── input power chart (source nodes) ────────────────────────────────────────
	let inpPowerContainer = $state(null);
	let inpPowerChart     = null;

	function buildPowerChart() {
		if (inpPowerChart) { inpPowerChart.destroy(); inpPowerChart = null; }
		if (!inpPowerContainer || !inputSeries) return;

		const sourceEntries = Object.entries(inputSeries).filter(([id]) => nodeKindMap[id] === 'source');
		if (sourceEntries.length === 0) return;

		const ts     = sourceEntries[0][1].t.map((s) => Date.parse(s) / 1000);
		const data   = [ts, ...sourceEntries.map(([, e]) => e.values.map((v) => (v === null ? NaN : v)))];
		const series = [{}, ...sourceEntries.map(([id, e], i) => (
			nodeSolarIds.has(id)
				? { label: e.label, ...SOLAR_STYLE }
				: { label: e.label, stroke: INP_COLORS[i % INP_COLORS.length], width: 1.5, spanGaps: false }
		))];
		inpPowerChart = makeUplot(inpPowerContainer, {
			width: inpPowerContainer.clientWidth || 800, height: 200,
			cursor: { show: true }, scales: { x: { time: true } }, series,
			axes: [AXIS_STYLE, { stroke: '#94a3b8', ticks: { stroke: '#334155' }, grid: { stroke: '#334155' }, label: 'W' }],
			legend: { show: true },
		}, data);
	}

	// ── residuals chart ───────────────────────────────────────────────────────
	let residContainer = $state(null);
	let residChart     = null;

	function buildResidChart() {
		if (residChart) { residChart.destroy(); residChart = null; }
		if (!residContainer || !simResult || !obsSeries) return;
		const validIds = Object.keys(obsSeries).filter((id) => simResult.nodes[id] !== undefined);
		if (validIds.length === 0) return;

		const simTs = simResult.t.map((s) => Date.parse(s));
		const ts    = simTs.map((ms) => ms / 1000);

		const residData = validIds.map((id) => {
			const obs     = obsSeries[id];
			const obsMs   = obs.t.map((s) => Date.parse(s));
			const simVals = simResult.nodes[id];
			return simTs.map((tms, k) => {
				const idx    = nearestIdx(obsMs, tms);
				const obsVal = idx >= 0 ? (obs.values[idx] ?? null) : null;
				return obsVal !== null ? (simVals[k] - obsVal) : NaN;
			});
		});

		const data   = [ts, ...residData];
		const series = [{}, ...validIds.map((id, i) => ({
			label: nodeLabels[id] ?? id, stroke: SIM_COLORS[i % SIM_COLORS.length], width: 1.5, spanGaps: false,
		}))];

		residChart = makeUplot(residContainer, {
			width: residContainer.clientWidth || 800, height: 200,
			cursor: { show: true }, scales: { x: { time: true } }, series,
			axes: [AXIS_STYLE, AXIS_Y_RESID],
			legend: { show: true },
		}, data);
	}

	// ── reactive chart builds ─────────────────────────────────────────────────
	$effect(() => { tempContainer; simResult; obsSeries; inputSeries; buildTempChart(); });
	$effect(() => { inpPowerContainer; inputSeries; buildPowerChart(); });
	$effect(() => { residContainer; simResult; obsSeries; buildResidChart(); });

	// ── resize observers ──────────────────────────────────────────────────────
	function watchResize(getContainer, getChart) {
		let obs;
		$effect(() => {
			const el = getContainer();
			if (!el) return;
			obs = new ResizeObserver(() => {
				const u = getChart();
				if (u && el) u.setSize({ width: el.clientWidth, height: u.height });
			});
			obs.observe(el);
			return () => obs?.disconnect();
		});
	}
	watchResize(() => tempContainer,     () => tempChart);
	watchResize(() => inpPowerContainer, () => inpPowerChart);
	watchResize(() => residContainer,    () => residChart);

	onDestroy(() => {
		tempChart?.destroy();
		inpPowerChart?.destroy();
		residChart?.destroy();
	});

	const hasPower = $derived(
		inputSeries && Object.keys(inputSeries).some((id) => nodeKindMap[id] === 'source')
	);
</script>

{#if simResult}
	{#if showMeta && simResult.meta}
		<div class="meta-block">
			<span class="meta-label">solver: {simResult.meta.solver}</span>
			<span class="meta-label">{simResult.t.length} steps</span>
			{#if simResult.meta.elapsed_s !== undefined}<span class="meta-label">{simResult.meta.elapsed_s.toFixed(2)} s</span>{/if}
			{#if simResult.meta.n_rhs_evals}<span class="meta-label">n_rhs_evals: {simResult.meta.n_rhs_evals}</span>{/if}
			{#if simResult.meta.success !== undefined}
				<span class:ok={simResult.meta.success} class:fail={!simResult.meta.success}>
					{simResult.meta.success ? '✓ success' : '✗ ' + simResult.meta.message}
				</span>
			{/if}
		</div>
	{/if}

	<div class="chart-section">
		<div class="section-title">
			Temperatures — mass nodes
			{#if hasObs}<span class="section-sub">simulated + observed overlay</span>{/if}
		</div>
		<div class="chart-wrap" bind:this={tempContainer}></div>
	</div>

	<div class="chart-section" class:hidden={!hasPower}>
		<div class="section-title">Input power</div>
		<div class="chart-wrap" bind:this={inpPowerContainer}></div>
	</div>

	<div class="chart-section" class:hidden={!hasObs}>
		<div class="section-title">
			Residuals
			<span class="section-sub">simulated − observed [°C]</span>
		</div>
		<div class="chart-wrap" bind:this={residContainer}></div>
	</div>
{/if}

<style>
	.meta-block {
		display: flex; gap: 16px; font-size: 11px; font-family: monospace;
		color: #94a3b8; padding: 4px 0; flex-wrap: wrap; flex-shrink: 0;
	}
	.meta-label { color: #64748b; }
	.meta-block .ok   { color: #4ade80; }
	.meta-block .fail { color: #f87171; }

	.chart-section { display: flex; flex-direction: column; gap: 6px; flex-shrink: 0; }
	.section-title {
		font-size: 12px; font-weight: 600; color: #94a3b8;
		text-transform: uppercase; letter-spacing: 0.05em;
		display: flex; align-items: baseline; gap: 8px;
	}
	.section-sub {
		font-size: 11px; font-weight: 400; color: #475569;
		text-transform: none; letter-spacing: 0;
	}
	.chart-wrap { flex-shrink: 0; }
	.hidden { display: none; }

	:global(.uplot)           { color: #94a3b8; }
	:global(.uplot canvas)    { background: #0f172a; }
	:global(.uplot .u-legend) { background: transparent; color: #94a3b8; font-size: 12px; }
</style>
