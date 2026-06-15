<script>
	// Merged study panel: the lumped-model (φ-space) table plus a forward run and
	// a fit, sharing one set of result charts. "Run forward" simulates from the
	// current nominals (with manual overrides); "Run fit" optimises the free
	// lumps and writes posteriors back onto the table.
	import SimCharts from '$lib/SimCharts.svelte';

	const API = '';

	let {
		house_name,
		study_id,
		inputs       = {},
		range        = { start: '', end: '' },
		observations = {},
		y0_uniform   = null,
		solver       = 'zoh',
		onRunSuccess = () => {},
	} = $props();

	// ── lumped-model (view) state ───────────────────────────────────────────────
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
			const res = await fetch(`${API}/houses/${house_name}/studies/${study_id}/view`, { method: 'POST' });
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
	$effect(() => { study_id; house_name; loadView(); });

	// ── view mutation (mode toggle + nominal override) ──────────────────────────
	let viewUpdatePending = $state(false);

	async function persistView(nextLumped) {
		view = { ...view, lumped: nextLumped };  // optimistic
		viewUpdatePending = true;
		try {
			const res = await fetch(`${API}/houses/${house_name}/studies/${study_id}/view`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ lumped: nextLumped }),
			});
			if (!res.ok) {
				const d = await res.json().catch(() => ({ detail: res.statusText }));
				throw new Error(typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail));
			}
			view = await res.json();
		} catch (e) {
			viewError = e.message;
			await loadView();  // revert
		} finally {
			viewUpdatePending = false;
		}
	}

	function toggleMode(lumpId) {
		if (!view || viewUpdatePending) return;
		const lump = view.lumped.find((l) => l.id === lumpId);
		if (!lump) return;
		const newMode = lump.mode === 'free' ? 'fixed' : 'free';
		persistView(view.lumped.map((l) => l.id === lumpId ? { ...l, mode: newMode } : l));
	}

	// Inline nominal edit — patches prior.nominal (or prior_C.nominal for the C
	// column of an RC_chain). Debounced so typing doesn't hammer the API.
	let nominalDebounce = null;
	function editNominal(lumpId, field, raw) {
		const value = parseFloat(raw);
		if (!view || isNaN(value) || value <= 0) return;
		const nextLumped = view.lumped.map((l) => {
			if (l.id !== lumpId) return l;
			const key = field === 'C' ? 'prior_C' : 'prior';
			const prior = { ...(l[key] ?? { sigma_log: 0.5 }), nominal: value };
			return { ...l, [key]: prior };
		});
		view = { ...view, lumped: nextLumped };  // optimistic, immediate
		clearTimeout(nominalDebounce);
		nominalDebounce = setTimeout(() => persistView(nextLumped), 400);
	}

	// ── input-data preview ───────────────────────────────────────────────────────
	// Health check on the configured input + observation signals over the current
	// range, before running. Catches missing / gappy / empty series loudly
	// (the silent flat-line failure mode in todo Step 5.5).
	let dataChecks  = $state(null);   // [{ id, role, signal, loading, error, meta }]
	let dataLoading = $state(false);

	const configuredSignals = $derived([
		...Object.entries(inputs)
			.filter(([, s]) => s?.trim())
			.map(([id, signal]) => ({ id, role: 'input', signal })),
		...Object.entries(observations)
			.filter(([, s]) => s?.trim())
			.map(([id, signal]) => ({ id, role: 'observation', signal })),
	]);

	function computeMeta(data) {
		const values = data.values;
		const valid  = values.filter((v) => v !== null);
		if (valid.length === 0)
			return { count: 0, total: values.length, gaps: 0, min: null, max: null, mean: null, empty: true };
		let gaps = 0, inGap = false;
		for (const v of values) {
			if (v === null) { if (!inGap) { gaps++; inGap = true; } } else { inGap = false; }
		}
		const sum = valid.reduce((a, b) => a + b, 0);
		return {
			count: valid.length, total: values.length, gaps, empty: false,
			min: Math.min(...valid), max: Math.max(...valid), mean: sum / valid.length,
		};
	}

	async function fetchInputs() {
		if (!range.start || !range.end || configuredSignals.length === 0) return;
		dataLoading = true;
		dataChecks = configuredSignals.map((s) => ({ ...s, loading: true, error: null, meta: null }));
		await Promise.all(dataChecks.map(async (row, i) => {
			try {
				const data = await fetchSeries(row.signal, range.start, range.end);
				dataChecks[i] = { ...row, loading: false, error: null, meta: computeMeta(data) };
			} catch (e) {
				dataChecks[i] = { ...row, loading: false, error: e.message, meta: null };
			}
		}));
		dataChecks = [...dataChecks];
		dataLoading = false;
		lastCheckedSnapshot = JSON.stringify({ range, inputs, observations });
	}

	// Mark the preview stale (clear it) when the range or signal config changes.
	let lastCheckedSnapshot = $state(null);
	$effect(() => {
		const snap = JSON.stringify({ range, inputs, observations });
		if (dataChecks !== null && snap !== lastCheckedSnapshot) dataChecks = null;
	});

	const hasDataIssue = $derived(
		(dataChecks ?? []).some((r) => r.error || r.meta?.empty || (r.meta?.gaps ?? 0) > 0)
	);

	const fmtMeta = (v) => (v === null || v === undefined ? '—' : v.toFixed(2));

	// ── fit config ──────────────────────────────────────────────────────────────
	let obsSigma = $state(0.5);
	let fitY0    = $state(false);

	// ── run state (shared by forward + fit) ──────────────────────────────────────
	let busy        = $state(false);
	let runError    = $state(null);
	let fitResult   = $state(null);   // last fit metadata (null for forward-only)
	let simResult   = $state(null);
	let inputSeries = $state(null);
	let obsSeries   = $state(null);

	const viewStale = $derived(view?._stale_view === true);
	const hasView   = $derived(view && (view.lumped?.length ?? 0) > 0);
	const hasFreeParams = $derived(view?.lumped?.some((l) => l.mode === 'free') ?? false);
	const hasObsCfg = $derived(Object.values(observations).some((v) => v?.trim()));

	const canForward = $derived(!busy && hasView && !viewStale && range.start && range.end);
	const canFit     = $derived(canForward && hasObsCfg && hasFreeParams);

	// ── series fetch ──────────────────────────────────────────────────────────
	async function fetchSeries(signal, start, end) {
		const url = `${API}/series?signal=${encodeURIComponent(signal)}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
		const res = await fetch(url);
		if (!res.ok) throw new Error(`Series fetch failed: ${res.statusText}`);
		return res.json();
	}

	function parseDetail(d) {
		const detail = d.detail;
		if (Array.isArray(detail)) return detail.map((e) => `${e.loc?.slice(1).join('.') || ''}: ${e.msg}`).join('; ');
		return typeof detail === 'string' ? detail : JSON.stringify(detail);
	}

	// Build node-field param_overrides from a fitted/forward atomic model.
	function nodeOverridesFromModel(model) {
		const ov = {};
		for (const n of (model?.nodes ?? [])) {
			if (n.kind === 'resistance' && n.R != null) ov[`${n.id}.R`] = n.R;
			if (n.kind === 'mass'       && n.C != null) ov[`${n.id}.C`] = n.C;
			if (n.kind === 'source'     && n.gain != null) ov[`${n.id}.gain`] = n.gain;
		}
		return ov;
	}

	async function runSim(paramOverrides, y0Override) {
		const body = {
			house_name, study_id,
			start: range.start, end: range.end,
			inputs, solver,
			param_overrides: paramOverrides ?? {},
			...(y0Override != null ? { y0_uniform: y0Override }
				: (y0_uniform != null ? { y0_uniform } : {})),
		};
		const res = await fetch(`${API}/simulate/run`, {
			method: 'POST', headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(body),
		});
		if (!res.ok) throw new Error(parseDetail(await res.json().catch(() => ({ detail: res.statusText }))));
		return res.json();
	}

	async function loadChartsFor(result) {
		simResult = result;
		const labels = Object.fromEntries((result.atomic_model?.nodes ?? []).map((n) => [n.id, n.label ?? n.id]));

		const fetchMap = async (map) => {
			const entries = await Promise.all(
				Object.entries(map).map(async ([nodeId, signal]) => {
					if (!signal) return null;
					try {
						const s = await fetchSeries(signal, range.start, range.end);
						return [nodeId, { t: s.t, values: s.values, label: labels[nodeId] ?? nodeId }];
					} catch { return null; }
				})
			);
			return Object.fromEntries(entries.filter(Boolean));
		};
		inputSeries = await fetchMap(inputs);
		obsSeries   = await fetchMap(observations);
	}

	function resetResults() {
		runError = null; fitResult = null; simResult = null; inputSeries = null; obsSeries = null;
	}

	// ── forward run (from current nominals / overrides) ─────────────────────────
	async function runForward() {
		if (!canForward) return;
		busy = true;
		resetResults();
		try {
			// Forward sim from the persisted nominals: the view already carries the
			// (possibly hand-edited) nominal values; expand() reproduces them, so an
			// empty override set runs the prior model as-is.
			const result = await runSim({});
			onRunSuccess();
			await loadChartsFor(result);
		} catch (e) {
			runError = e.message;
		} finally {
			busy = false;
		}
	}

	// ── fit run ─────────────────────────────────────────────────────────────────
	async function runFit() {
		if (!canFit) return;
		busy = true;
		resetResults();
		const body = {
			house_name, study_id,
			start: range.start, end: range.end,
			inputs,
			observations: Object.fromEntries(Object.entries(observations).filter(([, v]) => v?.trim())),
			obs_sigma: obsSigma,
			dt_minutes: 15,
			fit_y0: fitY0,
			...(y0_uniform != null ? { y0_uniform } : {}),
		};
		try {
			const res = await fetch(`${API}/fit/run`, {
				method: 'POST', headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body),
			});
			if (!res.ok) throw new Error(parseDetail(await res.json().catch(() => ({ detail: res.statusText }))));
			fitResult = await res.json();
			onRunSuccess();
			await loadView();  // pull persisted posteriors

			// Forward sim with the fitted model + fitted y₀ (if any).
			const result = await runSim(nodeOverridesFromModel(fitResult.atomic_model), fitResult.fitted_y0);
			await loadChartsFor(result);
		} catch (e) {
			runError = e.message;
		} finally {
			busy = false;
		}
	}

	// ── formatting ──────────────────────────────────────────────────────────────
	const KIND_COLORS = {
		RC_chain: '#22d3ee', Req: '#f97316', Ceq: '#a78bfa', T_boundary: '#94a3b8', Q_source: '#4ade80',
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
</script>

<div class="fit-panel">
	<!-- action bar -->
	<div class="action-bar">
		<label class="obs-sigma-label">
			<span>obs σ (°C)</span>
			<input type="number" bind:value={obsSigma} min="0.01" step="0.1" style="width:70px" />
		</label>

		<label class="checkbox-label" title="Fit a uniform initial temperature instead of using the fixed T₀">
			<input type="checkbox" bind:checked={fitY0} />
			<span>fit y₀</span>
		</label>

		<div class="run-group">
			<button class="run-btn run-forward" onclick={runForward} disabled={!canForward}>
				{busy ? '…' : 'Run forward'}
			</button>
			<button class="run-btn run-fit" onclick={runFit} disabled={!canFit}>
				{busy ? 'Working…' : 'Run fit'}
			</button>
		</div>
	</div>

	<div class="body">
		<!-- input-data section -->
		<section class="section">
			<div class="section-header">
				<span>Input data</span>
				{#if dataChecks && !hasDataIssue}<span class="data-ok">✓ ok</span>{/if}
				{#if dataChecks && hasDataIssue}<span class="data-warn">⚠ check signals</span>{/if}
				<button
					class="view-btn"
					onclick={fetchInputs}
					disabled={dataLoading || configuredSignals.length === 0 || !range.start || !range.end}
					title="Fetch the configured input and observation signals for the current range"
				>
					{dataLoading ? '…' : (dataChecks ? '⟳ Re-fetch' : 'Fetch inputs')}
				</button>
			</div>

			{#if configuredSignals.length === 0}
				<p class="hint">No signals assigned. Configure inputs/observations first.</p>
			{:else if !dataChecks}
				<p class="hint">{configuredSignals.length} signal{configuredSignals.length > 1 ? 's' : ''} configured. Click "Fetch inputs" to check coverage over {range.start || '…'} → {range.end || '…'}.</p>
			{:else}
				<table class="data-table">
					<thead>
						<tr>
							<th>Role</th><th>Signal</th><th>Samples</th><th>Gaps</th><th>Range (min / max / mean)</th>
						</tr>
					</thead>
					<tbody>
						{#each dataChecks as row (row.id + row.role)}
							<tr class:bad-row={row.error || row.meta?.empty}>
								<td><span class="role-badge role-{row.role}">{row.role}</span></td>
								<td class="sig" title={row.signal}>{row.signal}</td>
								{#if row.loading}
									<td colspan="3" class="muted">loading…</td>
								{:else if row.error}
									<td colspan="3" class="data-err">⚠ {row.error}</td>
								{:else if row.meta}
									<td class="num">
										{row.meta.count} / {row.meta.total}
										{#if row.meta.empty}<span class="data-err"> empty</span>{/if}
									</td>
									<td class="num">
										{#if row.meta.gaps > 0}<span class="gap-warn">{row.meta.gaps}</span>{:else}0{/if}
									</td>
									<td class="num">{fmtMeta(row.meta.min)} / {fmtMeta(row.meta.max)} / {fmtMeta(row.meta.mean)}</td>
								{/if}
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</section>

		<!-- lumped-model section -->
		<section class="section">
			<div class="section-header">
				<span>Lumped model</span>
				{#if view && !viewStale}
					<span class="hash-tag"># {view.model_hash?.slice(0, 8) ?? ''}</span>
				{/if}
				<button
					class="view-btn"
					class:stale={viewStale}
					onclick={buildView}
					disabled={viewLoading}
					title={view ? 'Rebuild the lumped model from the current house' : 'Build the lumped model'}
				>
					{viewLoading ? '…' : (view ? (viewStale ? '⚠ Rebuild model' : '⟳ Rebuild') : 'Build lumped model')}
				</button>
			</div>

			{#if viewError}<div class="error-box">{viewError}</div>{/if}
			{#if viewStale}
				<div class="stale-banner">⚠ House changed — the lumped model is stale. Rebuild before fitting.</div>
			{/if}

			{#if !view && !viewLoading}
				<p class="hint">No lumped model yet. Click "Build lumped model" to derive it from the current house.</p>
			{:else if view}
				<table class="phi-table">
					<thead>
						<tr>
							<th>Label</th>
							<th>Kind</th>
							<th>Connection</th>
							<th>Nominal R / Req</th>
							<th>Nominal C</th>
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
							{@const editable = lump.mode !== 'fixed'}
							{@const hasPosterior = lump.posterior != null}
							{@const shift = hasPosterior ? fmtShift(lump.posterior.value, lump.prior.nominal) : ''}
							{@const shiftC = lump.posterior_C && lump.prior_C ? fmtShift(lump.posterior_C.value, lump.prior_C.nominal) : ''}
							<tr class:fixed-row={lump.mode === 'fixed'}>
								<td class="lump-label" title={lump.id}>{lump.label ?? lump.id}</td>
								<td><span class="kind-badge" style="border-color:{color};color:{color}">{lump.kind}</span></td>
								<td class="conn">
									{#if lump.node_a || lump.node_b}
										<span class="node">{lump.node_a ?? '—'}</span>
										{#if lump.node_b}<span class="conn-sep">↔</span><span class="node">{lump.node_b}</span>{/if}
									{:else}
										<span class="muted">—</span>
									{/if}
								</td>
								<td class="num">
									{#if editable}
										<input
											class="nominal-input"
											type="number" step="any" min="0"
											value={lump.prior.nominal}
											onchange={(e) => editNominal(lump.id, 'R', e.currentTarget.value)}
										/>
									{:else}
										{fmtVal(lump.prior.nominal)}
									{/if}
									<span class="sigma">±{lump.prior.sigma_log.toFixed(2)}</span>
								</td>
								<td class="num">
									{#if lump.prior_C}
										{#if editable}
											<input
												class="nominal-input"
												type="number" step="any" min="0"
												value={lump.prior_C.nominal}
												onchange={(e) => editNominal(lump.id, 'C', e.currentTarget.value)}
											/>
										{:else}
											{fmtVal(lump.prior_C.nominal)}
										{/if}
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
										disabled={viewUpdatePending}
										title="Toggle free/fixed"
									>{lump.mode}</button>
								</td>
								{#if fitResult}
									<td class="num">
										{#if hasPosterior}
											<span class="posterior">{fmtVal(lump.posterior.value)}</span>
											<span class="sigma">±{lump.posterior.sigma_log.toFixed(2)}</span>
											{#if shift}<span class="shift" class:shift-large={Math.abs(parseFloat(shift)) > 30}>{shift}</span>{/if}
										{:else}<span class="muted">—</span>{/if}
									</td>
									<td class="num">
										{#if lump.posterior_C}
											<span class="posterior">{fmtVal(lump.posterior_C.value)}</span>
											<span class="sigma">±{lump.posterior_C.sigma_log.toFixed(2)}</span>
											{#if shiftC}<span class="shift" class:shift-large={Math.abs(parseFloat(shiftC)) > 30}>{shiftC}</span>{/if}
										{:else}<span class="muted">—</span>{/if}
									</td>
								{/if}
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</section>

		{#if runError}<div class="error-box">⚠ {runError}</div>{/if}

		{#if fitResult}
			<div class="result-meta-row">
				<span class="result-meta">
					{fitResult.method}
					{#if fitResult.elapsed_s !== undefined}· {fitResult.elapsed_s.toFixed(1)} s{/if}
					{#if fitResult.n_evals !== undefined}· {fitResult.n_evals} evals{/if}
					{#if fitResult.cost !== undefined}· cost {fitResult.cost.toFixed(4)}{/if}
					{#if fitResult.fitted_y0 != null}· y₀ {fitResult.fitted_y0.toFixed(2)} °C{/if}
					{#if fitResult.success !== undefined}
						<span class:ok={fitResult.success} class:fail={!fitResult.success}>
							· {fitResult.success ? '✓' : '✗ ' + fitResult.message}
						</span>
					{/if}
				</span>
			</div>
		{/if}

		{#if simResult}
			<SimCharts {simResult} {inputSeries} {obsSeries} />
		{/if}
	</div>
</div>

<style>
	.fit-panel {
		flex: 1; display: flex; flex-direction: column;
		min-height: 0; overflow: hidden; color: #f1f5f9;
	}

	.action-bar {
		display: flex; align-items: center; gap: 16px;
		padding: 10px 20px; background: #1e293b;
		border-bottom: 1px solid #334155; flex-shrink: 0;
	}

	.obs-sigma-label, .checkbox-label {
		display: flex; align-items: center; gap: 6px;
		font-size: 11px; text-transform: uppercase;
		letter-spacing: 0.06em; color: #94a3b8;
	}
	.checkbox-label { cursor: pointer; }
	.checkbox-label input { cursor: pointer; }

	.run-group { margin-left: auto; display: flex; gap: 8px; }
	.run-btn {
		color: #f1f5f9; border: none; border-radius: 4px;
		padding: 8px 16px; font-size: 13px; font-weight: 600;
		cursor: pointer; transition: background 0.15s;
	}
	.run-btn:disabled { opacity: 0.5; cursor: not-allowed; }
	.run-forward { background: #334155; }
	.run-forward:hover:not(:disabled) { background: #475569; }
	.run-fit { background: #4f46e5; }
	.run-fit:hover:not(:disabled) { background: #4338ca; }

	.body {
		flex: 1; overflow-y: auto; padding: 16px 20px;
		display: flex; flex-direction: column; gap: 20px; min-height: 0;
	}

	.section { display: flex; flex-direction: column; gap: 8px; }
	.section-header {
		font-size: 10px; font-weight: 700; text-transform: uppercase;
		letter-spacing: 0.08em; color: #94a3b8;
		display: flex; align-items: center; gap: 8px;
	}

	.hash-tag {
		font-family: monospace; font-weight: 400; font-size: 10px;
		color: #475569; text-transform: none; letter-spacing: 0;
	}

	.hint { font-size: 12px; color: #94a3b8; margin: 0; }

	input[type='number'] {
		background: #0f172a; color: #e2e8f0; border: 1px solid #334155;
		border-radius: 4px; padding: 4px 8px; font-size: 12px;
		font-family: monospace; box-sizing: border-box;
	}
	input:focus { outline: none; border-color: #6366f1; }

	.nominal-input { width: 96px; }

	.view-btn {
		background: #1e293b; border: 1px solid #334155; color: #64748b;
		font-size: 10px; font-weight: 600; padding: 3px 10px; border-radius: 4px;
		cursor: pointer; text-transform: uppercase; letter-spacing: 0.05em;
	}
	.view-btn:hover:not(:disabled) { background: #334155; color: #94a3b8; }
	.view-btn:disabled { opacity: 0.4; cursor: default; }
	.view-btn.stale { border-color: #92400e; color: #f59e0b; background: #1c1100; }
	.view-btn.stale:hover:not(:disabled) { background: #291900; }

	.stale-banner {
		font-size: 12px; color: #f59e0b; background: #1c1100;
		border: 1px solid #92400e; border-radius: 4px; padding: 8px 12px;
	}

	.phi-table { width: 100%; border-collapse: collapse; font-size: 12px; }
	.phi-table th {
		text-align: left; font-size: 10px; text-transform: uppercase;
		letter-spacing: 0.06em; color: #94a3b8;
		padding: 4px 8px 6px; border-bottom: 1px solid #334155;
	}
	.phi-table td { padding: 5px 8px; vertical-align: middle; }
	.phi-table tr.fixed-row { opacity: 0.55; }
	.phi-table tr:hover:not(.fixed-row) { background: #1e293b33; }

	.lump-label {
		font-size: 12px; color: #e2e8f0; max-width: 200px;
		overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
	}

	.kind-badge {
		font-size: 9px; font-weight: 700; text-transform: uppercase;
		letter-spacing: 0.05em; padding: 2px 5px; border-radius: 3px;
		border: 1px solid; white-space: nowrap;
	}

	.conn { font-size: 11px; color: #cbd5e1; white-space: nowrap; }
	.conn .node {
		display: inline-block; max-width: 110px; overflow: hidden;
		text-overflow: ellipsis; vertical-align: bottom;
	}
	.conn-sep { color: #475569; margin: 0 5px; }

	.num { font-family: monospace; color: #cbd5e1; white-space: nowrap; }
	.sigma { font-size: 10px; color: #475569; margin-left: 3px; }
	.muted { color: #334155; }
	.posterior { color: #38bdf8; font-weight: 600; }

	.shift { font-size: 10px; color: #a78bfa; margin-left: 4px; }
	.shift.shift-large { color: #f59e0b; }

	.mode-btn {
		font-size: 10px; font-weight: 700; text-transform: uppercase;
		letter-spacing: 0.05em; padding: 2px 8px; border-radius: 3px;
		border: 1px solid #334155; cursor: pointer; background: none; color: #64748b;
		transition: background 0.1s, color 0.1s, border-color 0.1s;
	}
	.mode-btn.mode-free  { border-color: #22d3ee44; color: #22d3ee; background: #0c2a2e; }
	.mode-btn.mode-fixed { border-color: #334155; color: #475569; background: none; }
	.mode-btn:hover:not(:disabled).mode-free  { background: #0e353a; }
	.mode-btn:hover:not(:disabled).mode-fixed { background: #1e293b; color: #64748b; }
	.mode-btn:disabled { opacity: 0.4; cursor: default; }

	.result-meta-row { padding: 4px 0; }
	.result-meta { font-size: 11px; color: #64748b; font-family: monospace; }
	.result-meta .ok   { color: #4ade80; }
	.result-meta .fail { color: #f87171; }

	.error-box {
		background: #1c0a0a; border: 1px solid #7f1d1d; border-radius: 4px;
		color: #f87171; padding: 12px 16px; font-size: 13px;
	}

	/* input-data table */
	.data-ok   { font-size: 10px; color: #4ade80; text-transform: none; letter-spacing: 0; }
	.data-warn { font-size: 10px; color: #f59e0b; text-transform: none; letter-spacing: 0; }

	.data-table { width: 100%; border-collapse: collapse; font-size: 12px; }
	.data-table th {
		text-align: left; font-size: 10px; text-transform: uppercase;
		letter-spacing: 0.06em; color: #94a3b8;
		padding: 4px 8px 6px; border-bottom: 1px solid #334155;
	}
	.data-table td { padding: 5px 8px; vertical-align: middle; }
	.data-table tr.bad-row { background: #1c0a0a55; }
	.data-table .sig {
		font-family: monospace; color: #cbd5e1; max-width: 220px;
		overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
	}
	.data-err { color: #f87171; }
	.gap-warn { color: #fbbf24; font-weight: 600; }

	.role-badge {
		font-size: 9px; font-weight: 700; text-transform: uppercase;
		letter-spacing: 0.05em; padding: 2px 5px; border-radius: 3px; border: 1px solid;
	}
	.role-input       { color: #4ade80; border-color: #4ade8044; }
	.role-observation { color: #818cf8; border-color: #818cf844; }
</style>
