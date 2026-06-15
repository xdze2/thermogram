<script>
	import { onDestroy } from 'svelte';
	import uPlot from 'uplot';
	import 'uplot/dist/uPlot.min.css';

	const API = '';

	let {
		house_name,
		study_id,
		inputs       = {},
		range        = { start: '', end: '' },
		observations = {},
		y0_uniform   = null,
		onready      = /** @type {(fn: () => void) => void} */ (() => {}),
	} = $props();

	$effect(() => { onready(runFit); });

	// ── view state ────────────────────────────────────────────────────────────
	let view         = $state(null);   // { lumped: [...], model_hash, _stale_view }
	let viewLoading  = $state(false);
	let viewError    = $state(null);

	async function loadView() {
		if (!house_name || !study_id) return;
		viewLoading = true;
		viewError   = null;
		try {
			const res = await fetch(`${API}/houses/${house_name}/studies/${study_id}/view`);
			if (res.status === 404) { view = null; return; }
			if (!res.ok) throw new Error(res.statusText);
			view = await res.json();
		} catch (e) {
			viewError = e.message;
		} finally {
			viewLoading = false;
		}
	}

	async function buildView() {
		if (!house_name || !study_id) return;
		viewLoading = true;
		viewError   = null;
		try {
			const res = await fetch(`${API}/houses/${house_name}/studies/${study_id}/view`, {
				method: 'POST',
			});
			if (!res.ok) {
				const d = await res.json().catch(() => ({ detail: res.statusText }));
				throw new Error(typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail));
			}
			view = await res.json();
		} catch (e) {
			viewError = e.message;
		} finally {
			viewLoading = false;
		}
	}

	// Load view when study changes
	$effect(() => {
		study_id;
		house_name;
		loadView();
	});

	// ── mode toggle ───────────────────────────────────────────────────────────
	let modeUpdatePending = $state(false);

	async function toggleMode(lumpId) {
		if (!view || modeUpdatePending) return;
		const lump = view.lumped.find((l) => l.id === lumpId);
		if (!lump) return;
		const newMode = lump.mode === 'free' ? 'fixed' : 'free';

		// Optimistic local update
		view = { ...view, lumped: view.lumped.map((l) => l.id === lumpId ? { ...l, mode: newMode } : l) };

		modeUpdatePending = true;
		try {
			const res = await fetch(`${API}/houses/${house_name}/studies/${study_id}/view`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ lumped: view.lumped }),
			});
			if (!res.ok) {
				const d = await res.json().catch(() => ({ detail: res.statusText }));
				throw new Error(typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail));
			}
			view = await res.json();
		} catch (e) {
			viewError = e.message;
			// revert
			await loadView();
		} finally {
			modeUpdatePending = false;
		}
	}

	// ── fit config ────────────────────────────────────────────────────────────
	let obsSigma = $state(0.5);

	// ── fit run ───────────────────────────────────────────────────────────────
	let fitLoading = $state(false);
	let fitError   = $state(null);
	let fitResult  = $state(null);

	const viewStale = $derived(view?._stale_view === true);
	const hasView   = $derived(view && (view.lumped?.length ?? 0) > 0);
	const hasFreeParams = $derived(
		view?.lumped?.some((l) => l.mode === 'free') ?? false
	);

	const canRun = $derived(
		!fitLoading &&
		hasView &&
		!viewStale &&
		range.start && range.end &&
		Object.values(observations).some((v) => v?.trim()) &&
		hasFreeParams
	);

	async function runFit() {
		if (!canRun) return;
		fitLoading  = true;
		fitError    = null;
		fitResult   = null;
		simResult   = null;
		inputSeries = null;
		obsSeries   = null;

		const body = {
			house_name,
			study_id,
			start:        range.start,
			end:          range.end,
			inputs,
			observations: Object.fromEntries(
				Object.entries(observations).filter(([, v]) => v?.trim())
			),
			obs_sigma:    obsSigma,
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

			// Reload view to get posteriors persisted by the API
			await loadView();

			// Forward sim using the fitted atomic_model returned by the API
			const simRes = await runSimWithFittedModel(fitResult.atomic_model);
			await loadChartsForResult(simRes);
		} catch (e) {
			fitError = e.message;
		} finally {
			fitLoading = false;
		}
	}

	// ── formatting helpers ────────────────────────────────────────────────────
	const KIND_COLORS = {
		RC_chain:   '#22d3ee',
		Req:        '#f97316',
		Ceq:        '#a78bfa',
		T_boundary: '#94a3b8',
		Q_source:   '#4ade80',
	};

	const KIND_UNITS = {
		RC_chain:   ['m²K/W', 'J/K'],
		Req:        ['m²K/W'],
		Ceq:        ['J/K'],
		T_boundary: ['°C'],
		Q_source:   ['W'],
	};

	function fmtVal(v) {
		if (v === null || v === undefined || (typeof v === 'number' && isNaN(v))) return '—';
		if (Math.abs(v) < 0.001 || Math.abs(v) >= 1e6) return v.toExponential(3);
		return v.toPrecision(4);
	}

	function fmtShift(fitted, nominal) {
		if (!nominal || fitted == null) return '';
		const pct = ((fitted - nominal) / nominal) * 100;
		return (pct >= 0 ? '+' : '') + pct.toFixed(0) + '%';
	}

	// ── post-fit simulation ───────────────────────────────────────────────────
	let simResult   = $state(null);
	let inputSeries = $state(null);
	let obsSeries   = $state(null);

	async function fetchSeries(signal, start, end) {
		const url = `${API}/series?signal=${encodeURIComponent(signal)}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
		const res = await fetch(url);
		if (!res.ok) throw new Error(`Series fetch failed: ${res.statusText}`);
		return res.json();
	}

	async function runSimWithFittedModel(fittedAtomicModel) {
		// The fit API returns atomic_model with fitted values already applied.
		// We need to run a forward sim — use param_overrides to carry the node values
		// derived from the fitted model's nodes.
		const nodeOverrides = {};
		for (const n of (fittedAtomicModel?.nodes ?? [])) {
			if (n.kind === 'resistance' && n.R != null) nodeOverrides[`${n.id}.R`] = n.R;
			if (n.kind === 'mass'       && n.C != null) nodeOverrides[`${n.id}.C`] = n.C;
			if (n.kind === 'source'     && n.gain != null) nodeOverrides[`${n.id}.gain`] = n.gain;
		}
		const body = {
			house_name,
			study_id,
			start:           range.start,
			end:             range.end,
			inputs,
			solver:          'zoh',
			param_overrides: nodeOverrides,
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

	const nodeKindMap = $derived.by(() => {
		if (!fitResult?.atomic_model) return {};
		return Object.fromEntries(
			(fitResult.atomic_model.nodes ?? []).map((n) => [n.id, n.kind])
		);
	});

	const nodeLabels = $derived.by(() => {
		if (!fitResult?.atomic_model) return {};
		return Object.fromEntries(
			(fitResult.atomic_model.nodes ?? []).map((n) => [n.id, n.label ?? n.id])
		);
	});

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

	// ── power inputs chart ────────────────────────────────────────────────────
	let inpPowerContainer = $state(null);
	let inpPowerChart     = null;

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
		<label class="obs-sigma-label">
			<span>obs σ (°C)</span>
			<input type="number" bind:value={obsSigma} min="0.01" step="0.1" style="width:70px" />
		</label>

		<button class="run-btn" onclick={runFit} disabled={!canRun}>
			{fitLoading ? 'Fitting…' : 'Run fit'}
		</button>
	</div>

	<div class="body">
		<!-- view section -->
		<section class="section">
			<div class="section-header">
				<span>φ-space view</span>
				{#if view && !viewStale}
					<span class="hash-tag"># {view.model_hash?.slice(0, 8) ?? ''}</span>
				{/if}
				<button
					class="view-btn"
					class:stale={viewStale}
					onclick={buildView}
					disabled={viewLoading}
					title={view ? 'Rebuild view from current model' : 'Build view'}
				>
					{viewLoading ? '…' : (view ? (viewStale ? '⚠ Rebuild view' : '⟳ Rebuild') : 'Build view')}
				</button>
			</div>

			{#if viewError}
				<div class="error-box">{viewError}</div>
			{/if}

			{#if viewStale}
				<div class="stale-banner">⚠ Model changed — view is stale. Rebuild before fitting.</div>
			{/if}

			{#if !view && !viewLoading}
				<p class="hint">No view built yet. Click "Build view" to create the φ-space from the current model.</p>
			{:else if view}
				<table class="phi-table">
					<thead>
						<tr>
							<th>Label</th>
							<th>Kind</th>
							<th>Prior R / Req</th>
							<th>Prior C</th>
							<th>Mode</th>
							{#if fitResult}
								<th>Posterior R / Req</th>
								<th>Posterior C</th>
							{/if}
						</tr>
					</thead>
					<tbody>
						{#each view.lumped as lump (lump.id)}
							{@const color = KIND_COLORS[lump.kind] ?? '#94a3b8'}
							{@const hasPosterior = lump.posterior != null}
							{@const shift = hasPosterior ? fmtShift(lump.posterior.value, lump.prior.nominal) : ''}
							{@const shiftC = lump.posterior_C && lump.prior_C ? fmtShift(lump.posterior_C.value, lump.prior_C.nominal) : ''}
							<tr class:fixed-row={lump.mode === 'fixed'}>
								<td class="lump-label" title={lump.id}>{lump.label ?? lump.id}</td>
								<td>
									<span class="kind-badge" style="border-color:{color};color:{color}">{lump.kind}</span>
								</td>
								<td class="num">
									{fmtVal(lump.prior.nominal)}
									<span class="sigma">±{lump.prior.sigma_log.toFixed(2)}</span>
								</td>
								<td class="num">
									{#if lump.prior_C}
										{fmtVal(lump.prior_C.nominal)}
										<span class="sigma">±{lump.prior_C.sigma_log.toFixed(2)}</span>
									{:else}
										<span class="muted">—</span>
									{/if}
								</td>
								<td>
									<button
										class="mode-btn"
										class:mode-free={lump.mode === 'free'}
										class:mode-fixed={lump.mode === 'fixed'}
										onclick={() => toggleMode(lump.id)}
										disabled={modeUpdatePending}
										title="Toggle free/fixed"
									>{lump.mode}</button>
								</td>
								{#if fitResult}
									<td class="num">
										{#if hasPosterior}
											<span class="posterior">{fmtVal(lump.posterior.value)}</span>
											<span class="sigma">±{lump.posterior.sigma_log.toFixed(2)}</span>
											{#if shift}
												<span class="shift" class:shift-large={Math.abs(parseFloat(shift)) > 30}>{shift}</span>
											{/if}
										{:else}
											<span class="muted">—</span>
										{/if}
									</td>
									<td class="num">
										{#if lump.posterior_C}
											<span class="posterior">{fmtVal(lump.posterior_C.value)}</span>
											<span class="sigma">±{lump.posterior_C.sigma_log.toFixed(2)}</span>
											{#if shiftC}
												<span class="shift" class:shift-large={Math.abs(parseFloat(shiftC)) > 30}>{shiftC}</span>
											{/if}
										{:else}
											<span class="muted">—</span>
										{/if}
									</td>
								{/if}
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</section>

		<!-- fit error -->
		{#if fitError}
			<div class="error-box">⚠ {fitError}</div>
		{/if}

		<!-- fit meta -->
		{#if fitResult}
			<div class="result-meta-row">
				<span class="result-meta">
					{fitResult.method}
					{#if fitResult.elapsed_s !== undefined}· {fitResult.elapsed_s.toFixed(1)} s{/if}
					{#if fitResult.n_evals !== undefined}· {fitResult.n_evals} evals{/if}
					{#if fitResult.cost !== undefined}· cost {fitResult.cost.toFixed(4)}{/if}
					{#if fitResult.success !== undefined}
						<span class:ok={fitResult.success} class:fail={!fitResult.success}>
							· {fitResult.success ? '✓' : '✗ ' + fitResult.message}
						</span>
					{/if}
				</span>
			</div>

			<!-- charts -->
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

	.hash-tag {
		font-family: monospace;
		font-weight: 400;
		font-size: 10px;
		color: #475569;
		text-transform: none;
		letter-spacing: 0;
	}

	.hint { font-size: 12px; color: #94a3b8; margin: 0; }

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

	/* ── view button ── */
	.view-btn {
		background: #1e293b;
		border: 1px solid #334155;
		color: #64748b;
		font-size: 10px;
		font-weight: 600;
		padding: 3px 10px;
		border-radius: 4px;
		cursor: pointer;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.view-btn:hover:not(:disabled) { background: #334155; color: #94a3b8; }
	.view-btn:disabled { opacity: 0.4; cursor: default; }
	.view-btn.stale {
		border-color: #92400e;
		color: #f59e0b;
		background: #1c1100;
	}
	.view-btn.stale:hover:not(:disabled) { background: #291900; }

	/* ── stale banner ── */
	.stale-banner {
		font-size: 12px;
		color: #f59e0b;
		background: #1c1100;
		border: 1px solid #92400e;
		border-radius: 4px;
		padding: 8px 12px;
	}

	/* ── φ-table ── */
	.phi-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 12px;
	}
	.phi-table th {
		text-align: left;
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #94a3b8;
		padding: 4px 8px 6px;
		border-bottom: 1px solid #334155;
	}
	.phi-table td { padding: 5px 8px; vertical-align: middle; }
	.phi-table tr.fixed-row { opacity: 0.45; }
	.phi-table tr:hover:not(.fixed-row) { background: #1e293b33; }

	.lump-label {
		font-size: 12px;
		color: #e2e8f0;
		max-width: 200px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.kind-badge {
		font-size: 9px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		padding: 2px 5px;
		border-radius: 3px;
		border: 1px solid;
		white-space: nowrap;
	}

	.num {
		font-family: monospace;
		color: #cbd5e1;
		white-space: nowrap;
	}

	.sigma {
		font-size: 10px;
		color: #475569;
		margin-left: 3px;
	}

	.muted { color: #334155; }

	.posterior { color: #38bdf8; font-weight: 600; }

	.shift {
		font-size: 10px;
		color: #a78bfa;
		margin-left: 4px;
	}
	.shift.shift-large { color: #f59e0b; }

	/* ── mode button ── */
	.mode-btn {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		padding: 2px 8px;
		border-radius: 3px;
		border: 1px solid #334155;
		cursor: pointer;
		background: none;
		color: #64748b;
		transition: background 0.1s, color 0.1s, border-color 0.1s;
	}
	.mode-btn.mode-free {
		border-color: #22d3ee44;
		color: #22d3ee;
		background: #0c2a2e;
	}
	.mode-btn.mode-fixed {
		border-color: #334155;
		color: #475569;
		background: none;
	}
	.mode-btn:hover:not(:disabled).mode-free  { background: #0e353a; }
	.mode-btn:hover:not(:disabled).mode-fixed { background: #1e293b; color: #64748b; }
	.mode-btn:disabled { opacity: 0.4; cursor: default; }

	/* ── result meta ── */
	.result-meta-row {
		padding: 4px 0;
	}
	.result-meta {
		font-size: 11px;
		color: #64748b;
		font-family: monospace;
	}
	.result-meta .ok   { color: #4ade80; }
	.result-meta .fail { color: #f87171; }

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
