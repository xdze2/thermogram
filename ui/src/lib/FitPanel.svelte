<script>
	import { onDestroy } from 'svelte';
	import uPlot from 'uplot';
	import 'uplot/dist/uPlot.min.css';

	const API = 'http://localhost:8001';

	let {
		house_name,
		study_id,
		model,
		inputs       = {},   // node_id → signal name (from Inputs tab)
		range        = { start: '', end: '' },
		observations = {},   // mass_node_id → signal name (from Inputs tab observations)
		groups       = [],   // list[list[str]] from /fit/preview-groups (all params)
		y0_uniform   = null, // null → auto; or a number [°C] for uniform initial state
		onready      = /** @type {(fn: () => void) => void} */ (() => {}),
	} = $props();

	$effect(() => { onready(runFit); });

	// Group colors — must match GraphView.svelte palette
	const GROUP_COLORS = ['#f97316', '#22d3ee', '#a78bfa', '#4ade80', '#fb7185'];

	// param_key → { color, groupIndex, size }
	const groupInfoMap = $derived.by(() => {
		const map = {};
		let colorIdx = 0;
		for (const g of groups) {
			if (g.length <= 1) { colorIdx; continue; }
			const color = GROUP_COLORS[colorIdx % GROUP_COLORS.length];
			colorIdx++;
			for (const key of g) map[key] = { color, size: g.length };
		}
		return map;
	});

	// ── params table ──────────────────────────────────────────────────────────
	// Each row: { key: 'node_id.field', nominal: number, sigma_log: number }
	let paramRows = $state([]);

	// Re-populate when model changes (keep existing rows, add missing ones)
	$effect(() => {
		if (!model) return;
		const nodes = model.nodes ?? [];
		const existing = new Set(paramRows.map((r) => r.key));
		const next = [...paramRows];

		for (const n of nodes) {
			if (n.kind === 'resistance' && !existing.has(`${n.id}.R`)) {
				next.push({ key: `${n.id}.R`, nominal: n.R ?? 0.01, sigma_log: 0.5 });
			} else if (n.kind === 'mass' && !existing.has(`${n.id}.C`)) {
				next.push({ key: `${n.id}.C`, nominal: n.C ?? 1_000_000, sigma_log: 0.5 });
			} else if (n.kind === 'source' && !existing.has(`${n.id}.gain`)) {
				next.push({ key: `${n.id}.gain`, nominal: n.gain ?? 1.0, sigma_log: 0.5 });
			}
		}
		// only update if something was actually added
		if (next.length !== paramRows.length) paramRows = next;
	});

	function toggleParam(key) {
		const idx = paramRows.findIndex((r) => r.key === key);
		if (idx === -1) return;
		paramRows = paramRows.map((r, i) =>
			i === idx ? { ...r, fixed: !r.fixed } : r
		);
	}

	function updateParam(key, field, raw) {
		const value = field === 'key' ? raw : parseFloat(raw);
		if (field !== 'key' && isNaN(value)) return;
		paramRows = paramRows.map((r) => r.key === key ? { ...r, [field]: value } : r);
	}

	// ── fit config ────────────────────────────────────────────────────────────
	let obsSigma = $state(0.5);
	let method   = $state('nls');

	// ── fit run ───────────────────────────────────────────────────────────────
	let fitLoading = $state(false);
	let fitError   = $state(null);
	let fitResult  = $state(null);

	const canRun = $derived(
		!fitLoading &&
		range.start && range.end &&
		Object.values(observations).some((v) => v?.trim()) &&
		paramRows.some((r) => !r.fixed)
	);

	async function runFit() {
		if (!canRun) return;
		fitLoading  = true;
		fitError    = null;
		fitResult   = null;
		simResult   = null;
		inputSeries = null;
		obsSeries   = null;

		const freeParams = {};
		for (const r of paramRows) {
			if (!r.fixed) freeParams[r.key] = { nominal: r.nominal, sigma_log: r.sigma_log };
		}

		const body = {
			house_name,
			study_id,
			start:        range.start,
			end:          range.end,
			inputs,
			observations: Object.fromEntries(
				Object.entries(observations).filter(([, v]) => v?.trim())
			),
			params:       freeParams,
			obs_sigma:    obsSigma,
			method,
			dt_minutes:   15,
			...(y0_uniform != null ? { y0_uniform } : {}),
		};

		try {
			const res = await fetch(`${API}/fit/run`, {
				method:  'POST',
				headers: { 'Content-Type': 'application/json' },
				body:    JSON.stringify(body),
			});
			if (!res.ok) {
				const d = await res.json().catch(() => ({ detail: res.statusText }));
				const detail = d.detail;
				const msg = Array.isArray(detail)
					? detail.map((e) => `${e.loc?.slice(1).join('.')||''}: ${e.msg}`).join('; ')
					: (typeof detail === 'string' ? detail : JSON.stringify(detail));
				throw new Error(msg);
			}
			fitResult = await res.json();

			// run forward simulation with fitted params to build charts
			const fittedParams = fitResult.params_fitted ?? fitResult.params_mean ?? {};
			const simRes = await runSimWithFittedParams(fittedParams);
			await loadChartsForResult(simRes);
		} catch (e) {
			fitError = e.message;
		} finally {
			fitLoading = false;
		}
	}

	// ── param label helpers ───────────────────────────────────────────────────
	const FIELD_UNITS = { R: 'm²K/W', C: 'J/K', gain: 'W/W' };
	const FIELD_LABEL = { R: 'R', C: 'C', gain: 'gain' };

	const nodeLabels = $derived(
		Object.fromEntries((model?.nodes ?? []).map((n) => [n.id, n.label ?? n.id]))
	);

	function fmtParamKey(key) {
		const dot = key.lastIndexOf('.');
		if (dot === -1) return key;
		const nodeId = key.slice(0, dot);
		const field  = key.slice(dot + 1);
		const label  = nodeLabels[nodeId] ?? nodeId;
		const unit   = FIELD_UNITS[field];
		return unit ? `${label}  [${unit}]` : `${label}.${field}`;
	}

	// ── results table helpers ─────────────────────────────────────────────────
	function fmtParam(v) {
		if (v === null || v === undefined || isNaN(v)) return '—';
		if (Math.abs(v) < 0.001 || Math.abs(v) >= 1e6) return v.toExponential(3);
		return v.toPrecision(4);
	}

	function pctChange(fitted, nominal) {
		if (!nominal) return '—';
		const pct = ((fitted - nominal) / nominal) * 100;
		return (pct >= 0 ? '+' : '') + pct.toFixed(1) + '%';
	}

	// ── post-fit simulation + series ──────────────────────────────────────────
	let simResult   = $state(null);
	let inputSeries = $state(null);
	let obsSeries   = $state(null);

	async function fetchSeries(signal, start, end) {
		const url = `${API}/series?signal=${encodeURIComponent(signal)}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
		const res = await fetch(url);
		if (!res.ok) throw new Error(`Series fetch failed: ${res.statusText}`);
		return res.json();
	}

	async function runSimWithFittedParams(fittedParams) {
		const body = {
			house_name,
			study_id,
			start:           range.start,
			end:             range.end,
			inputs,
			solver:          'zoh',
			param_overrides: fittedParams,
			...(y0_uniform != null ? { y0_uniform } : {}),
		};
		const res = await fetch(`${API}/simulate/run`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(body),
		});
		if (!res.ok) {
			const d = await res.json().catch(() => ({ detail: res.statusText }));
			const detail = d.detail;
			const msg = Array.isArray(detail)
				? detail.map((e) => `${e.loc?.slice(1).join('.')||''}: ${e.msg}`).join('; ')
				: (typeof detail === 'string' ? detail : JSON.stringify(detail));
			throw new Error(msg);
		}
		return res.json();
	}

	async function loadChartsForResult(result) {
		simResult = result;

		const inputEntries = await Promise.all(
			Object.entries(inputs).map(async ([nodeId, signal]) => {
				try {
					const s = await fetchSeries(signal, range.start, range.end);
					return [nodeId, { t: s.t, values: s.values, label: nodeLabels[nodeId] ?? nodeId }];
				} catch { return null; }
			})
		);
		inputSeries = Object.fromEntries(inputEntries.filter(Boolean));

		const obsEntries = await Promise.all(
			Object.entries(observations).map(async ([nodeId, signal]) => {
				if (!signal) return null;
				try {
					const s = await fetchSeries(signal, range.start, range.end);
					return [nodeId, { t: s.t, values: s.values, label: nodeLabels[nodeId] ?? nodeId }];
				} catch { return null; }
			})
		);
		obsSeries = Object.fromEntries(obsEntries.filter(Boolean));
	}

	// ── uPlot helpers ─────────────────────────────────────────────────────────
	const SIM_COLORS  = ['#38bdf8', '#fb923c', '#a78bfa', '#34d399', '#f472b6', '#facc15'];
	const OBS_COLORS  = ['#fde68a', '#fca5a5', '#d9f99d', '#e9d5ff'];
	const INP_COLORS  = ['#64748b', '#475569', '#94a3b8', '#6b7280', '#9ca3af'];

	const AXIS_STYLE   = { stroke: '#94a3b8', ticks: { stroke: '#334155' }, grid: { stroke: '#1e293b' } };
	const AXIS_Y       = { stroke: '#94a3b8', ticks: { stroke: '#334155' }, grid: { stroke: '#334155' }, label: '°C' };
	const AXIS_Y_RESID = { stroke: '#94a3b8', ticks: { stroke: '#334155' }, grid: { stroke: '#334155' }, label: 'Δ°C' };

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
			label: id, stroke: SIM_COLORS[i % SIM_COLORS.length], width: 1.5, spanGaps: false,
		}));
		const simData = massIds.map((id) => simResult.nodes[id].map((v) => (v === null ? NaN : v)));

		const obsIds = obsSeries ? Object.keys(obsSeries).filter((id) => simResult.nodes[id] !== undefined) : [];
		const obsSer = obsIds.map((id, i) => ({
			label: `${id} (obs)`,
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

	const nodeKindMap = $derived(
		Object.fromEntries((model?.nodes ?? []).map((n) => [n.id, n.kind]))
	);

	function buildPowerChart() {
		if (inpPowerChart) { inpPowerChart.destroy(); inpPowerChart = null; }
		if (!inpPowerContainer || !inputSeries) return;

		const entries = Object.entries(inputSeries).filter(([id]) => nodeKindMap[id] === 'source').map(([, e]) => e);
		if (entries.length === 0) return;

		const ts     = entries[0].t.map((s) => Date.parse(s) / 1000);
		const data   = [ts, ...entries.map((e) => e.values.map((v) => (v === null ? NaN : v)))];
		const series = [{}, ...entries.map((e, i) => ({
			label: e.label, stroke: INP_COLORS[i % INP_COLORS.length], width: 1.5, spanGaps: false,
		}))];
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
			label: id, stroke: SIM_COLORS[i % SIM_COLORS.length], width: 1.5, spanGaps: false,
		}))];

		residChart = makeUplot(residContainer, {
			width: residContainer.clientWidth || 800, height: 200,
			cursor: { show: true }, scales: { x: { time: true } }, series,
			axes: [AXIS_STYLE, AXIS_Y_RESID],
			legend: { show: true },
		}, data);
	}

	// ── reactive chart builds ─────────────────────────────────────────────────
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

<div class="fit-panel">
	<!-- action bar -->
	<div class="action-bar">
		<div class="method-group">
			<label class="radio-label">
				<input type="radio" bind:group={method} value="nls" />
				<span>NLS</span>
			</label>
			<label class="radio-label">
				<input type="radio" bind:group={method} value="mcmc" />
				<span>MCMC</span>
			</label>
		</div>

		<label class="obs-sigma-label">
			<span>obs σ (°C)</span>
			<input type="number" bind:value={obsSigma} min="0.01" step="0.1" style="width:70px" />
		</label>

		<button class="run-btn" onclick={runFit} disabled={!canRun}>
			{fitLoading ? 'Fitting…' : 'Run fit'}
		</button>
	</div>

	<div class="body">
		<!-- params section -->
		<section class="section">
			<div class="section-header">Free parameters</div>

			{#if paramRows.length === 0}
				<p class="hint">No parameters found. Load a study first.</p>
			{:else}
				<table class="params-table">
					<thead>
						<tr>
							<th></th>
							<th>Parameter</th>
							<th></th>
							<th>Nominal</th>
							<th>σ log</th>
						</tr>
					</thead>
					<tbody>
						{#each paramRows as row (row.key)}
							{@const gi = groupInfoMap[row.key]}
							<tr class:fixed={row.fixed}>
								<td>
									<input
										type="checkbox"
										checked={!row.fixed}
										onchange={() => toggleParam(row.key)}
									/>
								</td>
								<td class="param-key" title={row.key}>{fmtParamKey(row.key)}</td>
								<td class="group-cell">
									{#if gi}
										<span class="group-dot" style="background:{gi.color}" title="Tied group — {gi.size} parallel paths"></span>
									{/if}
								</td>
								<td>
									<input
										type="number"
										value={row.nominal}
										step="any"
										disabled={row.fixed}
										onchange={(e) => updateParam(row.key, 'nominal', e.target.value)}
									/>
								</td>
								<td>
									<input
										type="number"
										value={row.sigma_log}
										min="0.05" max="5" step="0.05"
										disabled={row.fixed}
										onchange={(e) => updateParam(row.key, 'sigma_log', e.target.value)}
									/>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</section>

		<!-- results section -->
		{#if fitError}
			<div class="error-box">⚠ {fitError}</div>
		{/if}

		{#if fitResult}
			<section class="section">
				<div class="section-header">
					Results
					<span class="result-meta">
						{fitResult.method}
						{#if fitResult.elapsed_s !== undefined}· {fitResult.elapsed_s.toFixed(1)} s{/if}
						{#if fitResult.n_evals !== undefined}· {fitResult.n_evals} evals{/if}
						{#if fitResult.success !== undefined}
							<span class:ok={fitResult.success} class:fail={!fitResult.success}>
								· {fitResult.success ? '✓' : '✗ ' + fitResult.message}
							</span>
						{/if}
					</span>
				</div>

				<table class="results-table">
					<thead>
						<tr>
							<th>Parameter</th>
							<th></th>
							<th>Old (nominal)</th>
							<th>New (fitted)</th>
							<th>± σ</th>
							<th>Δ</th>
						</tr>
					</thead>
					<tbody>
						{#each Object.keys(fitResult.params_nominal ?? fitResult.params_mean ?? {}) as key}
							{@const nominal = fitResult.params_nominal?.[key]}
							{@const fitted  = (fitResult.params_fitted ?? fitResult.params_mean)?.[key]}
							{@const std     = fitResult.params_std?.[key]}
							{@const gi      = groupInfoMap[key]}
							<tr>
								<td class="param-key" title={key}>{fmtParamKey(key)}</td>
								<td class="group-cell">
									{#if gi}
										<span class="group-dot" style="background:{gi.color}" title="Tied — shared multiplier with {gi.size - 1} other path(s)"></span>
									{/if}
								</td>
								<td class="num">{fmtParam(nominal)}</td>
								<td class="num fitted">{fmtParam(fitted)}</td>
								<td class="num std">± {fmtParam(std)}</td>
								<td class="num change">{pctChange(fitted, nominal)}</td>
							</tr>
						{/each}
					</tbody>
				</table>

				{#if fitResult.cost !== undefined}
					<div class="cost-row">cost (½ RSS): {fitResult.cost.toFixed(4)}</div>
				{/if}
				{#if fitResult.acceptance_rate !== undefined}
					<div class="cost-row">acceptance rate: {(fitResult.acceptance_rate * 100).toFixed(1)}%</div>
				{/if}
			</section>

			<!-- charts — fitted simulation vs observed -->
			{#if simResult}
				<section class="section">
					<div class="section-header">
						Temperatures — fitted simulation
						{#if hasObs}<span class="chart-sub">simulated + observed overlay</span>{/if}
					</div>
					<div class="chart-wrap" bind:this={tempContainer}></div>
				</section>

				<section class="section" class:hidden={!inputSeries || !Object.keys(inputSeries).some((id) => nodeKindMap[id] === 'source')}>
					<div class="section-header">Input power</div>
					<div class="chart-wrap" bind:this={inpPowerContainer}></div>
				</section>

				<section class="section" class:hidden={!hasObs}>
					<div class="section-header">
						Residuals
						<span class="chart-sub">simulated − observed [°C]</span>
					</div>
					<div class="chart-wrap" bind:this={residContainer}></div>
				</section>
			{/if}
		{/if}
	</div>
</div>

<style>
	.fit-panel {
		flex: 1;
		display: flex;
		flex-direction: column;
		min-height: 0;
		overflow: hidden;
		color: #f1f5f9;
	}

	.action-bar {
		display: flex;
		align-items: center;
		gap: 16px;
		padding: 10px 20px;
		background: #1e293b;
		border-bottom: 1px solid #334155;
		flex-shrink: 0;
	}

	.method-group { display: flex; gap: 14px; }

	.radio-label {
		display: flex; align-items: center; gap: 5px; cursor: pointer;
	}
	.radio-label span { font-size: 12px; color: #e2e8f0; }

	.obs-sigma-label {
		display: flex; align-items: center; gap: 6px;
		font-size: 11px; text-transform: uppercase;
		letter-spacing: 0.06em; color: #94a3b8;
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

	.body {
		flex: 1;
		overflow-y: auto;
		padding: 16px 20px;
		display: flex;
		flex-direction: column;
		gap: 20px;
		min-height: 0;
	}

	.section {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.section-header {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: #94a3b8;
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.hint { font-size: 12px; color: #94a3b8; margin: 0; }

	input[type='text'],
	input[type='number'] {
		background: #0f172a;
		color: #e2e8f0;
		border: 1px solid #334155;
		border-radius: 4px;
		padding: 4px 8px;
		font-size: 12px;
		font-family: monospace;
		box-sizing: border-box;
	}
	input:focus { outline: none; border-color: #6366f1; }
	input:disabled { opacity: 0.4; }

	/* params table */
	.params-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 12px;
	}
	.params-table th {
		text-align: left;
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #94a3b8;
		padding: 4px 8px 6px;
		border-bottom: 1px solid #334155;
	}
	.params-table td { padding: 4px 8px; }
	.params-table tr.fixed { opacity: 0.45; }
	.params-table tr:hover:not(.fixed) { background: #1e293b33; }

	.params-table input[type='number'] { width: 110px; }
	.params-table input[type='checkbox'] { cursor: pointer; accent-color: #6366f1; }

	.param-key {
		font-size: 12px;
		color: #e2e8f0;
		max-width: 280px;
	}

	.group-cell {
		width: 14px;
		padding: 4px 2px;
	}

	.group-dot {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
		cursor: help;
	}

	/* results table */
	.results-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 12px;
	}
	.results-table th {
		text-align: left;
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #94a3b8;
		padding: 4px 8px 6px;
		border-bottom: 1px solid #334155;
	}
	.results-table td { padding: 5px 8px; }
	.results-table tr:nth-child(even) { background: #1e293b44; }

	.num { font-family: monospace; color: #cbd5e1; }
	.fitted { color: #38bdf8; font-weight: 600; }
	.std { color: #94a3b8; }
	.change { color: #a78bfa; }

	.result-meta {
		font-size: 11px;
		font-weight: 400;
		text-transform: none;
		letter-spacing: 0;
		color: #64748b;
	}
	.result-meta .ok   { color: #4ade80; }
	.result-meta .fail { color: #f87171; }

	.cost-row {
		font-size: 11px;
		font-family: monospace;
		color: #64748b;
		padding: 2px 8px;
	}

	.error-box {
		background: #1c0a0a;
		border: 1px solid #7f1d1d;
		border-radius: 4px;
		color: #f87171;
		padding: 12px 16px;
		font-size: 13px;
	}

	.chart-wrap { flex-shrink: 0; }
	.chart-sub {
		font-size: 11px;
		font-weight: 400;
		text-transform: none;
		letter-spacing: 0;
		color: #475569;
	}
	.hidden { display: none; }

	:global(.uplot)           { color: #94a3b8; }
	:global(.uplot canvas)    { background: #0f172a; }
	:global(.uplot .u-legend) { background: transparent; color: #94a3b8; font-size: 12px; }
</style>
