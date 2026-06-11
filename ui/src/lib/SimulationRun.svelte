<script>
	import { onMount, onDestroy } from 'svelte';
	import uPlot from 'uplot';
	import 'uplot/dist/uPlot.min.css';

	const API = '';

	let {
		house_name,
		study_id,
		inputs       = {},
		range        = { start: '', end: '' },
		observations = {},
		solver       = $bindable('zoh'),
		y0_uniform   = null,   // null → auto; or a number [°C] for uniform initial state
		simStale     = false,
		onRunSuccess = () => {},
		hideControls = false,
		onready      = /** @type {(fn: () => void) => void} */ (() => {}),
	} = $props();

	$effect(() => { onready(runSimulation); });

	// ── simulation ────────────────────────────────────────────────────────────
	let simLoading   = $state(false);
	let simError     = $state(null);
	let simResult    = $state(null);
	let inputSeries  = $state(null);  // { node_id: { t, values, label } }
	let obsSeries    = $state(null);  // { node_id: { t, values, label } }

	async function fetchSeries(signal, start, end) {
		const url = `${API}/series?signal=${encodeURIComponent(signal)}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
		const res = await fetch(url);
		if (!res.ok) throw new Error(`Series fetch failed: ${res.statusText}`);
		return res.json();
	}

	async function runSimulation() {
		simLoading  = true;
		simError    = null;
		simResult   = null;
		inputSeries = null;
		obsSeries   = null;
		try {
			const body = { house_name, study_id, start: range.start, end: range.end, inputs, solver, ...(y0_uniform != null ? { y0_uniform } : {}) };
			const res  = await fetch(`${API}/simulate/run`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body),
			});
			if (!res.ok) {
				const d = await res.json().catch(() => ({ detail: res.statusText }));
				const detail = d.detail;
				const msg = Array.isArray(detail)
					? detail.map((e) => `${e.loc?.slice(1).join('.')||''}: ${e.msg}`).join('; ')
					: (typeof detail === 'object' && detail !== null ? JSON.stringify(detail) : (detail ?? res.statusText));
				throw new Error(msg);
			}
			simResult = await res.json();
			onRunSuccess();

			// fetch input series in parallel
			const inputEntries = await Promise.all(
				Object.entries(inputs).map(async ([nodeId, signal]) => {
					try {
						const s = await fetchSeries(signal, range.start, range.end);
						return [nodeId, { t: s.t, values: s.values, label: nodeLabels[nodeId] ?? nodeId, signal }];
					} catch { return null; }
				})
			);
			inputSeries = Object.fromEntries(inputEntries.filter(Boolean));

			// fetch observation series in parallel (if any)
			const obsEntries = await Promise.all(
				Object.entries(observations).map(async ([nodeId, signal]) => {
					if (!signal) return null;
					try {
						const s = await fetchSeries(signal, range.start, range.end);
						return [nodeId, { t: s.t, values: s.values, label: nodeLabels[nodeId] ?? nodeId, signal }];
					} catch { return null; }
				})
			);
			obsSeries = Object.fromEntries(obsEntries.filter(Boolean));
		} catch (e) {
			simError = e.message;
		} finally {
			simLoading = false;
		}
	}

	// ── uPlot helpers ─────────────────────────────────────────────────────────
	const SIM_COLORS  = ['#38bdf8', '#fb923c', '#a78bfa', '#34d399', '#f472b6', '#facc15'];
	const OBS_COLORS  = ['#fde68a', '#fca5a5', '#d9f99d', '#e9d5ff'];
	const INP_COLORS  = ['#64748b', '#475569', '#94a3b8', '#6b7280', '#9ca3af'];

	const AXIS_STYLE  = { stroke: '#94a3b8', ticks: { stroke: '#334155' }, grid: { stroke: '#1e293b' } };
	const AXIS_Y      = { stroke: '#94a3b8', ticks: { stroke: '#334155' }, grid: { stroke: '#334155' }, label: '°C' };
	const AXIS_Y_RESID = { stroke: '#94a3b8', ticks: { stroke: '#334155' }, grid: { stroke: '#334155' }, label: 'Δ°C' };

	function makeUplot(container, opts, data) {
		return new uPlot(opts, data, container);
	}

	// ── temperature chart ─────────────────────────────────────────────────────
	let tempContainer = $state(null);
	let tempChart     = null;
	// unwrapped DOM refs for uPlot (avoids Svelte 5 proxy wrapping)

	function buildTempChart() {
		if (tempChart) { tempChart.destroy(); tempChart = null; }
		if (!tempContainer || !simResult) return;

		const ts      = simResult.t.map((s) => Date.parse(s) / 1000);
		const massIds = Object.keys(simResult.nodes);
		const simTsMs = simResult.t.map((s) => Date.parse(s));

		const simSeries = massIds.map((id, i) => ({
			label: nodeLabels[id] ?? id,
			stroke: SIM_COLORS[i % SIM_COLORS.length],
			width: 1.5,
			spanGaps: false,
			show: !nodeWallMassIds.has(id),
		}));
		const simData = massIds.map((id) => simResult.nodes[id].map((v) => (v === null ? NaN : v)));

		// overlay observed temperatures if available
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

		// overlay boundary input temperatures
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

	// ── power inputs chart (source nodes) ────────────────────────────────────
	let inpPowerContainer = $state(null);
	let inpPowerChart     = null;

	const rcNodes = $derived(simResult?.rc_model?.nodes ?? []);
	const nodeKindMap   = $derived(
		Object.fromEntries(rcNodes.map((n) => [n.id, n.kind]))
	);
	const nodeLabels    = $derived(
		Object.fromEntries(rcNodes.map((n) => [n.id, n.label ?? n.id]))
	);
	const nodeSolarIds  = $derived(
		new Set(rcNodes.filter((n) => n.id.startsWith('solar_')).map((n) => n.id))
	);
	// Wall mass nodes (inertial lump nodes) — hidden by default in the temperature chart
	const nodeWallMassIds = $derived(
		new Set(rcNodes.filter((n) => n.kind === 'mass' && n.id.startsWith('m_')).map((n) => n.id))
	);

	const SOLAR_STYLE = { stroke: '#ca8a04', fill: 'rgba(234,179,8,0.18)', width: 1, spanGaps: false };

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

	function nearestIdx(sortedMs, tms) {
		if (sortedMs.length === 0) return -1;
		let lo = 0, hi = sortedMs.length - 1;
		while (lo < hi) {
			const mid = (lo + hi) >> 1;
			if (sortedMs[mid] < tms) lo = mid + 1; else hi = mid;
		}
		return lo;
	}

	function buildResidChart() {
		if (residChart) { residChart.destroy(); residChart = null; }
		if (!residContainer || !simResult || !obsSeries) return;
		const validIds = Object.keys(obsSeries).filter((id) => simResult.nodes[id] !== undefined);
		if (validIds.length === 0) return;

		const simTs   = simResult.t.map((s) => Date.parse(s));
		const ts      = simTs.map((ms) => ms / 1000);

		const residData = validIds.map((id) => {
			const obs   = obsSeries[id];
			const obsMs = obs.t.map((s) => Date.parse(s));
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
		return;
	}

	// ── reactive chart builds ─────────────────────────────────────────────────
	// Explicitly read container $state refs so Svelte tracks them — effects
	// re-run both when data arrives and when the DOM node is bound.
	$effect(() => {
		// eslint-disable-next-line no-unused-expressions
		tempContainer; simResult; obsSeries; inputSeries;
		buildTempChart();
	});
	$effect(() => {
		// eslint-disable-next-line no-unused-expressions
		inpPowerContainer; inputSeries;
		buildPowerChart();
	});
	$effect(() => {
		// eslint-disable-next-line no-unused-expressions
		residContainer; simResult; obsSeries;
		buildResidChart();
	});

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
	watchResize(() => tempContainer,      () => tempChart);
	watchResize(() => inpPowerContainer, () => inpPowerChart);
	watchResize(() => residContainer,    () => residChart);

	onDestroy(() => {
		tempChart?.destroy();
		inpPowerChart?.destroy();
		residChart?.destroy();
	});

	const hasObs = $derived(obsSeries && Object.keys(obsSeries).length > 0);
</script>

<div class="run-panel">
	<!-- action bar (hidden when parent owns controls) -->
	{#if !hideControls}
	<div class="action-bar">
		<div class="solver-group">
			<label class="radio-label">
				<input type="radio" bind:group={solver} value="ivp" />
				<span>IVP (BDF)</span>
			</label>
			<label class="radio-label">
				<input type="radio" bind:group={solver} value="zoh" />
				<span>ZOH</span>
			</label>
		</div>
		<button class="run-btn" onclick={runSimulation} disabled={simLoading}>
			{simLoading ? 'Running…' : simResult && simStale ? 'Re-run' : 'Run simulation'}
		</button>
	</div>
	{/if}

	<!-- results -->
	<div class="results">
		{#if simStale && simResult && !simLoading}
			<div class="stale-banner">⚠ Results are outdated — inputs or model changed since last run.</div>
		{/if}

		{#if !simResult && !simLoading && !simError}
			<div class="empty">Configure inputs, then click Run.</div>

		{:else if simLoading}
			<div class="status-msg">Running simulation…</div>

		{:else if simError}
			<div class="error-box">⚠ {simError}</div>

		{:else if simResult}
			<!-- meta row -->
			{#if simResult.meta}
				<div class="meta-block">
					<span class="meta-label">solver: {simResult.meta.solver}</span>
					<span class="meta-label">{simResult.t.length} steps</span>
					<span class="meta-label">{simResult.meta.elapsed_s.toFixed(2)} s</span>
					{#if simResult.meta.n_rhs_evals}<span class="meta-label">n_rhs_evals: {simResult.meta.n_rhs_evals}</span>{/if}
					<span class:ok={simResult.meta.success} class:fail={!simResult.meta.success}>
						{simResult.meta.success ? '✓ success' : '✗ ' + simResult.meta.message}
					</span>
				</div>
			{/if}

			<!-- temperatures + observed overlay -->
			<div class="chart-section">
				<div class="section-title">
					Temperatures — mass nodes
					{#if hasObs}<span class="section-sub">simulated + observed overlay</span>{/if}
				</div>
				<div class="chart-wrap" bind:this={tempContainer}></div>
			</div>

			<!-- input power (source nodes) -->
			<div class="chart-section" class:hidden={!inputSeries || !Object.keys(inputSeries).some((id) => nodeKindMap[id] === 'source')}>
				<div class="section-title">Input power</div>
				<div class="chart-wrap" bind:this={inpPowerContainer}></div>
			</div>

			<!-- residuals — always rendered so bind:this is stable; hidden when no obs -->
			<div class="chart-section" class:hidden={!hasObs}>
				<div class="section-title">
					Residuals
					<span class="section-sub">simulated − observed [°C]</span>
				</div>
				<div class="chart-wrap" bind:this={residContainer}></div>
			</div>
		{/if}
	</div>
</div>

<style>
	.run-panel {
		flex: 1;
		display: flex;
		flex-direction: column;
		min-height: 0;
		overflow: hidden;
	}

	.action-bar {
		display: flex;
		align-items: center;
		gap: 16px;
		padding: 12px 20px;
		background: #1e293b;
		border-bottom: 1px solid #334155;
		flex-shrink: 0;
	}

	.solver-group {
		display: flex;
		gap: 14px;
	}

	.radio-label {
		display: flex;
		align-items: center;
		gap: 5px;
		cursor: pointer;
	}
	.radio-label span {
		font-size: 12px;
		color: #e2e8f0;
	}

	.run-btn {
		background: #4f46e5; color: #f1f5f9;
		border: none; border-radius: 4px;
		padding: 8px 16px; font-size: 13px; font-weight: 600;
		cursor: pointer; transition: background 0.15s;
		margin-left: auto;
	}
	.run-btn:hover:not(:disabled) { background: #4338ca; }
	.run-btn:disabled { opacity: 0.5; cursor: not-allowed; }

	.results {
		flex: 1;
		display: flex;
		flex-direction: column;
		padding: 20px 24px;
		gap: 20px;
		overflow-y: auto;
		min-height: 0;
	}

	.empty {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
		color: #94a3b8;
		font-size: 14px;
	}

	.stale-banner {
		background: #1c1400;
		border: 1px solid #78350f;
		border-radius: 4px;
		color: #fcd34d;
		font-size: 12px;
		padding: 8px 12px;
		flex-shrink: 0;
	}

	.status-msg { font-size: 13px; color: #94a3b8; padding: 8px 0; }

	.error-box {
		background: #1c0a0a; border: 1px solid #7f1d1d;
		border-radius: 4px; color: #f87171; padding: 12px 16px; font-size: 13px;
	}

	.meta-block {
		display: flex; gap: 16px; font-size: 11px; font-family: monospace;
		color: #94a3b8; padding: 4px 0; flex-wrap: wrap; flex-shrink: 0;
	}
	.meta-label { color: #64748b; }
	.meta-block .ok   { color: #4ade80; }
	.meta-block .fail { color: #f87171; }

	.chart-section {
		display: flex;
		flex-direction: column;
		gap: 6px;
		flex-shrink: 0;
	}

	.section-title {
		font-size: 12px;
		font-weight: 600;
		color: #94a3b8;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		display: flex;
		align-items: baseline;
		gap: 8px;
	}

	.section-sub {
		font-size: 11px;
		font-weight: 400;
		color: #475569;
		text-transform: none;
		letter-spacing: 0;
	}

	.chart-wrap { flex-shrink: 0; }
	.hidden { display: none; }

	:global(.uplot)          { color: #94a3b8; }
	:global(.uplot canvas)   { background: #0f172a; }
	:global(.uplot .u-legend){ background: transparent; color: #94a3b8; font-size: 12px; }
</style>
