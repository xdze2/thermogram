<script>
	// Card-per-LumpedElement view of a study's φ-space (View.lumped), sourced from
	// /houses/{name}/studies/{id}/view — the same data FitPanel's phi-table reads.
	// This is the "lumped layer" the RC Graph tab should show instead of the raw
	// atomic expand() mesh (see docs/todo_2.md). Mirrors FitPanel's view state
	// management (load/build/persist/toggle/edit) independently for now.

	const API = '';

	let { house_name, study_id } = $props();

	let view        = $state(null);   // { lumped: [...], model_hash, _stale_view }
	let viewLoading = $state(false);
	let viewError   = $state(null);

	async function loadView() {
		if (!house_name || !study_id) { view = null; return; }
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

	$effect(() => { study_id; house_name; loadView(); });

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

	const viewStale = $derived(view?._stale_view === true);

	const KIND_COLORS = {
		RC_chain: '#22d3ee', Req: '#f97316', Ceq: '#a78bfa', T_boundary: '#94a3b8', Q_source: '#4ade80',
	};

	function fmtVal(v) {
		if (v === null || v === undefined || (typeof v === 'number' && isNaN(v))) return '—';
		if (Math.abs(v) < 0.001 || Math.abs(v) >= 1e6) return v.toExponential(3);
		return v.toPrecision(4);
	}

	// Group cards by node_a for display only — same LumpedElement objects, no
	// duplication, just a sectioning of the one list (docs/todo_2.md).
	const groups = $derived.by(() => {
		if (!view) return [];
		const byNode = new Map();
		for (const lump of view.lumped) {
			const key = lump.node_a ?? '—';
			if (!byNode.has(key)) byNode.set(key, []);
			byNode.get(key).push(lump);
		}
		return [...byNode.entries()].sort(([a], [b]) => a.localeCompare(b));
	});
</script>

<div class="lumped-view">
	<div class="lumped-view-header">
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
		{#each groups as [nodeA, lumps] (nodeA)}
			<div class="lump-group">
				<div class="lump-group-header">{nodeA}</div>
				<div class="lump-cards">
					{#each lumps as lump (lump.id)}
						{@const color = KIND_COLORS[lump.kind] ?? '#94a3b8'}
						{@const editable = lump.mode !== 'fixed'}
						<div class="lump-card" class:fixed-card={lump.mode === 'fixed'}>
							<div class="lump-card-top">
								<span class="lump-label" title={lump.id}>{lump.label ?? lump.id}</span>
								<span class="kind-badge" style="border-color:{color};color:{color}">{lump.kind}</span>
							</div>
							<div class="lump-conn">
								{#if lump.node_a || lump.node_b}
									<span class="node">{lump.node_a ?? '—'}</span>
									{#if lump.node_b}<span class="conn-sep">↔</span><span class="node">{lump.node_b}</span>{/if}
								{:else}
									<span class="muted">—</span>
								{/if}
							</div>
							<div class="lump-fields">
								<div class="lump-field">
									<span class="field-label">R / Req</span>
									{#if editable}
										<input
											class="nominal-input"
											type="number" step="any" min="0"
											value={lump.prior.nominal}
											onchange={(e) => editNominal(lump.id, 'R', e.currentTarget.value)}
										/>
									{:else}
										<span class="field-value">{fmtVal(lump.prior.nominal)}</span>
									{/if}
									<span class="sigma">±{lump.prior.sigma_log.toFixed(2)}</span>
								</div>
								{#if lump.prior_C}
									<div class="lump-field">
										<span class="field-label">C</span>
										{#if editable}
											<input
												class="nominal-input"
												type="number" step="any" min="0"
												value={lump.prior_C.nominal}
												onchange={(e) => editNominal(lump.id, 'C', e.currentTarget.value)}
											/>
										{:else}
											<span class="field-value">{fmtVal(lump.prior_C.nominal)}</span>
										{/if}
										<span class="sigma">±{lump.prior_C.sigma_log.toFixed(2)}</span>
									</div>
								{/if}
							</div>
							<button
								class="mode-btn"
								class:mode-free={lump.mode === 'free'}
								class:mode-fixed={lump.mode === 'fixed'}
								onclick={() => toggleMode(lump.id)}
								disabled={viewUpdatePending}
								title="Toggle free/fixed"
							>{lump.mode}</button>
						</div>
					{/each}
				</div>
			</div>
		{/each}
	{/if}
</div>

<style>
	.lumped-view { display: flex; flex-direction: column; gap: 12px; padding: 10px; overflow-y: auto; height: 100%; }
	.lumped-view-header { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; color: #e2e8f0; }
	.hash-tag { font-size: 11px; color: #64748b; font-family: monospace; }
	.hint { font-size: 12px; color: #94a3b8; margin: 0; }
	.error-box { font-size: 12px; color: #f87171; background: #1c0a0a; border: 1px solid #7f1d1d; border-radius: 4px; padding: 6px 8px; }
	.stale-banner { font-size: 12px; color: #f59e0b; background: #1c1100; border: 1px solid #92400e; border-radius: 4px; padding: 6px 8px; }

	.view-btn {
		margin-left: auto;
		font-size: 11px; padding: 3px 8px; border-radius: 4px;
		border: 1px solid #334155; background: #1e293b; color: #cbd5e1; cursor: pointer;
	}
	.view-btn:hover:not(:disabled) { background: #334155; color: #94a3b8; }
	.view-btn:disabled { opacity: 0.4; cursor: default; }
	.view-btn.stale { border-color: #92400e; color: #f59e0b; background: #1c1100; }
	.view-btn.stale:hover:not(:disabled) { background: #291900; }

	.lump-group-header {
		font-size: 11px; font-weight: 600; color: #64748b; text-transform: uppercase;
		letter-spacing: 0.03em; margin-bottom: 6px;
	}
	.lump-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 8px; }

	.lump-card {
		display: flex; flex-direction: column; gap: 6px;
		border: 1px solid #334155; border-radius: 6px; padding: 8px;
		background: #0f172a;
	}
	.lump-card.fixed-card { opacity: 0.6; }

	.lump-card-top { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
	.lump-label { font-size: 12px; font-weight: 600; color: #e2e8f0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.kind-badge { font-size: 10px; border: 1px solid; border-radius: 3px; padding: 1px 5px; white-space: nowrap; }

	.lump-conn { font-size: 11px; color: #94a3b8; display: flex; gap: 4px; align-items: center; }
	.conn-sep { color: #475569; }
	.muted { color: #475569; }

	.lump-fields { display: flex; flex-direction: column; gap: 4px; }
	.lump-field { display: flex; align-items: center; gap: 6px; font-size: 11px; }
	.field-label { color: #64748b; width: 42px; flex-shrink: 0; }
	.field-value { color: #cbd5e1; font-family: monospace; }
	.sigma { color: #475569; font-size: 10px; }

	.nominal-input {
		width: 70px; font-size: 11px; font-family: monospace;
		background: #1e293b; border: 1px solid #334155; border-radius: 3px;
		color: #e2e8f0; padding: 1px 4px;
	}

	.mode-btn {
		align-self: flex-start; font-size: 10px; padding: 1px 6px; border-radius: 3px;
		border: 1px solid #334155; background: #1e293b; cursor: pointer;
	}
	.mode-btn.mode-free { color: #4ade80; border-color: #166534; }
	.mode-btn.mode-fixed { color: #94a3b8; border-color: #334155; }
</style>
