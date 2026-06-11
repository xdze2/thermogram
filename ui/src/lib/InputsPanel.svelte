<script>
	import { onMount, onDestroy } from 'svelte';
	import SignalPicker from '$lib/SignalPicker.svelte';
	import uPlot from 'uplot';
	import 'uplot/dist/uPlot.min.css';

	const API = 'http://localhost:8001';

	// ── props (bound from parent) ─────────────────────────────────────────────
	let {
		model,
		inputs       = $bindable({}),
		range        = $bindable({ start: '', end: '' }),
		observations = $bindable({}),  // mass_node_id → signal name (empty string = unknown)
	} = $props();

	// ── boundary/source nodes ─────────────────────────────────────────────────
	const inputNodes = $derived(
		(model?.nodes ?? []).filter((n) => n.kind === 'boundary' || n.kind === 'source')
	);

	// ── mass nodes (observations) ─────────────────────────────────────────────
	const massNodes = $derived(
		(model?.nodes ?? []).filter((n) => n.kind === 'mass')
	);

	function setObs(nodeId, value) {
		observations = { ...observations, [nodeId]: value };
	}

	function isObsMeasured(nodeId) {
		// "measured" when the checkbox is on; presence of non-empty signal implies measured
		return (observations[nodeId] ?? null) !== null;
	}

	function toggleObsCheckbox(nodeId) {
		if (isObsMeasured(nodeId)) {
			// remove from map → unknown
			const next = { ...observations };
			delete next[nodeId];
			observations = next;
		} else {
			// add to map with empty string → measured (but no signal yet)
			observations = { ...observations, [nodeId]: '' };
		}
	}

	// ── signal autocomplete ───────────────────────────────────────────────────
	let signals      = $state([]);
	let signalsError = $state(false);

	async function loadSignals() {
		try {
			const res = await fetch(`${API}/signals`);
			if (!res.ok) throw new Error(res.statusText);
			signals      = await res.json();
			signalsError = false;
		} catch {
			signalsError = true;
		}
	}

	function setInput(nodeId, value) {
		inputs = { ...inputs, [nodeId]: value };
	}

	// ── stale tracking ────────────────────────────────────────────────────────
	// snapshot of (range + inputs) at the time of the last successful preview
	let previewedSnapshot = $state(null);

	function currentSnapshot() {
		return JSON.stringify({ range, inputs, observations });
	}

	const isStale = $derived(
		previewedSnapshot !== null && previewedSnapshot !== currentSnapshot()
	);

	// ── signal previews (inputs + measured observations) ─────────────────────
	let previews    = $state({});
	let anyLoading  = $derived(Object.values(previews).some((p) => p.loading));

	async function fetchOne(id, signal) {
		const params = new URLSearchParams({ signal, start: range.start, end: range.end });
		const res    = await fetch(`${API}/series?${params}`);
		if (!res.ok) {
			const d = await res.json().catch(() => ({ detail: res.statusText }));
			throw new Error(d.detail ?? res.statusText);
		}
		return res.json();
	}

	async function previewAll() {
		const inputEntries = inputNodes
			.filter((n) => inputs[n.id]?.trim() && range.start && range.end)
			.map((n) => ({ id: n.id, signal: inputs[n.id] }));

		const obsEntries = massNodes
			.filter((n) => observations[n.id]?.trim() && range.start && range.end)
			.map((n) => ({ id: n.id, signal: observations[n.id] }));

		const allEntries = [...inputEntries, ...obsEntries];
		if (allEntries.length === 0) return;

		// mark all as loading
		const loading = {};
		for (const { id } of allEntries) loading[id] = { loading: true, error: null, data: null, meta: null };
		previews = loading;

		await Promise.all(allEntries.map(async ({ id, signal }) => {
			try {
				const data = await fetchOne(id, signal);
				previews = { ...previews, [id]: { loading: false, error: null, data, meta: computeMeta(data) } };
			} catch (e) {
				previews = { ...previews, [id]: { loading: false, error: e.message, data: null, meta: null } };
			}
		}));

		previewedSnapshot = currentSnapshot();
	}

	function computeMeta(data) {
		const values = data.values;
		const valid  = values.filter((v) => v !== null);
		if (valid.length === 0)
			return { count: 0, total: values.length, gaps: 0, min: null, max: null, mean: null };
		let gaps = 0, inGap = false;
		for (const v of values) {
			if (v === null) { if (!inGap) { gaps++; inGap = true; } } else { inGap = false; }
		}
		const sum = valid.reduce((a, b) => a + b, 0);
		return {
			count: valid.length, total: values.length, gaps,
			min: Math.min(...valid), max: Math.max(...valid), mean: sum / valid.length,
		};
	}

	function fmt(v) { return v === null || v === undefined ? '—' : v.toFixed(2); }

	// ── uPlot charts (one per node) ───────────────────────────────────────────
	let chartContainers = $state({});  // nodeId → DOM element
	const uplots = {};                 // nodeId → uPlot instance

	function buildChart(nodeId, el, data) {
		if (uplots[nodeId]) { uplots[nodeId].destroy(); delete uplots[nodeId]; }
		if (!el || !data) return;
		const ts = data.t.map((s) => Date.parse(s) / 1000);
		const vs = data.values.map((v) => (v === null ? NaN : v));
		uplots[nodeId] = new uPlot({
			width: el.clientWidth || 700, height: 180,
			cursor: { show: true }, scales: { x: { time: true } },
			series: [
				{},
				{ label: data.signal, stroke: '#38bdf8', width: 1.5, spanGaps: false },
			],
			axes: [
				{ stroke: '#94a3b8', ticks: { stroke: '#334155' }, grid: { stroke: '#1e293b' } },
				{ stroke: '#94a3b8', ticks: { stroke: '#334155' }, grid: { stroke: '#334155' } },
			],
		}, [ts, vs], el);
	}

	$effect(() => {
		for (const [nodeId, el] of Object.entries(chartContainers)) {
			const p = previews[nodeId];
			if (el && p?.data) buildChart(nodeId, el, p.data);
		}
	});

	const canPreview = $derived(
		range.start && range.end && (
			inputNodes.some((n) => inputs[n.id]?.trim()) ||
			massNodes.some((n) => observations[n.id]?.trim())
		)
	);

	onMount(loadSignals);
	onDestroy(() => { for (const u of Object.values(uplots)) u.destroy(); });
</script>

<div class="inputs-panel">
	<!-- date range + preview button -->
	<div class="top-bar">
		<div>
			<div class="section-header" style="margin-top:0">Date range</div>
			<div class="date-row">
				<label>
					<span>From</span>
					<input type="date" bind:value={range.start} class:missing={!range.start} />
				</label>
				<label>
					<span>To</span>
					<input type="date" bind:value={range.end} class:missing={!range.end} />
				</label>
			</div>
		</div>

		<button
			class="preview-all-btn"
			class:stale={isStale}
			disabled={!canPreview || anyLoading}
			onclick={previewAll}
		>
			{anyLoading ? 'Loading…' : isStale ? 'Preview ●' : 'Preview'}
		</button>
	</div>

	<!-- signal assignment -->
	<div class="section-header">
		Inputs
		{#if signalsError}<span class="sig-warn" title="Cannot reach API">⚠</span>{/if}
	</div>


	{#if !model}
		<p class="hint">No study loaded.</p>
	{:else if inputNodes.length === 0}
		<p class="hint">No boundary or source nodes in this model.</p>
	{:else}
		<div class="node-rows">
			{#each inputNodes as node}
				{@const p = previews[node.id]}
				<div class="node-block">
					<div class="node-row">
						<div class="node-label">
							<span class="kind-dot kind-{node.kind}"></span>
							<span class="node-name">{node.label ?? node.id}</span>
							<span class="node-id">{node.id}</span>
						</div>
						<SignalPicker
							{signals}
							value={inputs[node.id] ?? ''}
							onpick={(v) => setInput(node.id, v)}
						/>
					</div>

					{#if p}
						<div class="preview-block">
							{#if p.loading}
								<div class="preview-status">Loading…</div>
							{:else if p.error}
								<div class="preview-status error">⚠ {p.error}</div>
							{:else if p.data}
								{#if p.meta}
									<div class="meta-row">
										<span>{p.meta.count} / {p.meta.total} samples</span>
										{#if p.meta.gaps > 0}
											<span class="gap-warn">{p.meta.gaps} gap{p.meta.gaps > 1 ? 's' : ''}</span>
										{/if}
										<span>min {fmt(p.meta.min)} · max {fmt(p.meta.max)} · mean {fmt(p.meta.mean)}</span>
									</div>
								{/if}
								<div class="chart-wrap" bind:this={chartContainers[node.id]}></div>
							{/if}
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}

	<!-- observations section -->
	{#if model && massNodes.length > 0}
		<div class="section-header" style="margin-top:8px">Observations</div>
		<div class="node-rows">
			{#each massNodes as node}
				{@const measured = isObsMeasured(node.id)}
				{@const p = previews[node.id]}
				<div class="node-block">
					<div class="node-row">
						<div class="node-label">
							<button
								class="obs-chip"
								class:measured
								onclick={() => toggleObsCheckbox(node.id)}
								title={measured ? 'Click to mark as unknown' : 'Click to mark as measured'}
							>{measured ? 'measured' : 'unknown'}</button>
							<span class="kind-dot kind-mass"></span>
							<span class="node-name">{node.label ?? node.id}</span>
							<span class="node-id">{node.id}</span>
						</div>
						{#if measured}
							<SignalPicker
								{signals}
								value={observations[node.id] ?? ''}
								onpick={(v) => setObs(node.id, v)}
							/>
						{/if}
					</div>

					{#if p}
						<div class="preview-block">
							{#if p.loading}
								<div class="preview-status">Loading…</div>
							{:else if p.error}
								<div class="preview-status error">⚠ {p.error}</div>
							{:else if p.data}
								{#if p.meta}
									<div class="meta-row">
										<span>{p.meta.count} / {p.meta.total} samples</span>
										{#if p.meta.gaps > 0}
											<span class="gap-warn">{p.meta.gaps} gap{p.meta.gaps > 1 ? 's' : ''}</span>
										{/if}
										<span>min {fmt(p.meta.min)} · max {fmt(p.meta.max)} · mean {fmt(p.meta.mean)}</span>
									</div>
								{/if}
								<div class="chart-wrap" bind:this={chartContainers[node.id]}></div>
							{/if}
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.inputs-panel {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 16px 20px;
		overflow-y: auto;
		color: #f1f5f9;
	}

	.top-bar {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		gap: 16px;
		margin-bottom: 4px;
	}

	.section-header {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: #94a3b8;
		margin-top: 10px;
		margin-bottom: 2px;
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.sig-warn { color: #f59e0b; font-size: 11px; }

	.date-row { display: flex; gap: 16px; }

	label {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	label > span {
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #94a3b8;
	}

	input[type='date'],
	input[type='text'] {
		background: #0f172a;
		color: #e2e8f0;
		border: 1px solid #334155;
		border-radius: 4px;
		padding: 4px 8px;
		font-size: 12px;
		font-family: monospace;
		box-sizing: border-box;
		color-scheme: dark;
	}
	input:focus { outline: none; border-color: #6366f1; }
	input.missing { border-color: #7f1d1d; color: #f87171; }
	input.missing::placeholder { color: #f87171; opacity: 0.5; }

	.preview-all-btn {
		background: #0f172a;
		border: 1px solid #334155;
		color: #94a3b8;
		border-radius: 4px;
		padding: 6px 14px;
		font-size: 12px;
		font-weight: 600;
		cursor: pointer;
		flex-shrink: 0;
		transition: color 0.1s, border-color 0.1s, background 0.1s;
		white-space: nowrap;
	}
	.preview-all-btn:hover:not(:disabled) { color: #f1f5f9; background: #1e293b; }
	.preview-all-btn:disabled { opacity: 0.3; cursor: not-allowed; }
	.preview-all-btn.stale { color: #fbbf24; border-color: #92400e; }
	.preview-all-btn.stale:hover:not(:disabled) { background: #1c1007; }

	.hint { font-size: 12px; color: #94a3b8; margin: 0; }

	/* node blocks */
	.node-rows { display: flex; flex-direction: column; gap: 8px; }

	.node-block {
		background: #1e293b;
		border: 1px solid #334155;
		border-radius: 6px;
		overflow: hidden;
	}

	.node-row {
		padding: 10px 12px;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.node-label { display: flex; align-items: center; gap: 5px; }

	.kind-dot {
		width: 7px; height: 7px;
		border-radius: 50%; flex-shrink: 0;
	}
	.kind-dot.kind-boundary { background: #4ade80; }
	.kind-dot.kind-source   { background: #fbbf24; }
	.kind-dot.kind-mass     { background: #818cf8; }

	.node-name {
		font-size: 12px; color: #e2e8f0; font-weight: 500;
		flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
	}
	.node-id { font-size: 10px; font-family: monospace; color: #94a3b8; flex-shrink: 0; }

	.preview-block {
		border-top: 1px solid #334155;
		padding: 10px 12px;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.preview-status { font-size: 12px; color: #94a3b8; }
	.preview-status.error { color: #f87171; }

	.meta-row {
		display: flex;
		gap: 16px;
		flex-wrap: wrap;
		font-size: 11px;
		color: #94a3b8;
	}
	.gap-warn { color: #fbbf24; }

	.chart-wrap { flex-shrink: 0; }

	.obs-chip {
		font-size: 10px;
		font-weight: 700;
		font-family: inherit;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		padding: 2px 7px;
		border-radius: 10px;
		border: 1px solid #334155;
		background: #0f172a;
		color: #475569;
		cursor: pointer;
		flex-shrink: 0;
		transition: background 0.1s, color 0.1s, border-color 0.1s;
		line-height: 1.6;
	}
	.obs-chip:hover { border-color: #475569; color: #94a3b8; }
	.obs-chip.measured {
		background: #1e1b4b;
		border-color: #4f46e5;
		color: #a5b4fc;
	}
	.obs-chip.measured:hover { background: #312e81; }

	:global(.uplot)          { color: #94a3b8; }
	:global(.uplot canvas)   { background: #0f172a; }
	:global(.uplot .u-legend){ background: transparent; color: #94a3b8; font-size: 12px; }
</style>
