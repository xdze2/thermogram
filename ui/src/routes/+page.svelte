<script>
	import { onMount } from 'svelte';
	import GraphView from '$lib/GraphView.svelte';
	import PropertiesPanel from '$lib/PropertiesPanel.svelte';
	import InputsPanel from '$lib/InputsPanel.svelte';
	import SimulationRun from '$lib/SimulationRun.svelte';
	import FitPanel from '$lib/FitPanel.svelte';
	import HousePanel from '$lib/HousePanel.svelte';
	import MaterialsPanel from '$lib/MaterialsPanel.svelte';
	import RangeSelect from '$lib/RangeSelect.svelte';

	const API = '';

	// ── navigation ────────────────────────────────────────────────────────────
	// activeSection: 'materials' | 'houses' | 'house'
	// simPaneTab: right-pane tab: 'studies' | 'sim' | 'rc' | 'topology' | 'inputs' | 'run' | 'fit' | 'debug'
	let activeSection = $state('houses');

	// ── houses list ───────────────────────────────────────────────────────────
	let housesList     = $state([]);
	let housesError    = $state(null);

	async function loadHousesList() {
		try {
			const res = await fetch(`${API}/houses`);
			if (!res.ok) throw new Error(res.statusText);
			housesList  = await res.json();
			housesError = null;
		} catch (e) {
			housesError = e.message;
		}
	}

	// ── current house ─────────────────────────────────────────────────────────
	let houseName          = $state(null);  // name of the currently open house
	let house              = $state(null);
	let houseSavedSnapshot = $state(null);
	const houseDirty = $derived(houseSavedSnapshot !== null && JSON.stringify(house) !== houseSavedSnapshot);
	let houseSaveLoading = $state(false);
	let houseSaveError   = $state(null);

	async function loadHouse(name) {
		try {
			const res = await fetch(`${API}/houses/${name}`);
			if (!res.ok) throw new Error(res.statusText);
			house              = await res.json();
			houseName          = name;
			houseSavedSnapshot = JSON.stringify(house);
			loadAtomicModel();
		} catch (e) {
			alert(`Failed to load house: ${e.message}`);
		}
	}

	async function openHouse(name) {
		await loadHouse(name);
		activeSection = 'house';
	}

	async function saveHouse() {
		if (!houseName) return;
		houseSaveLoading = true;
		houseSaveError   = null;
		// Strip computed fields (_model_hash, _stale_*) before saving
		const toSave = stripComputed(house);
		try {
			const res = await fetch(`${API}/houses/${houseName}`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(toSave),
			});
			if (!res.ok) {
				const d = await res.json().catch(() => ({}));
				throw new Error(d.detail ?? res.statusText);
			}
			houseSavedSnapshot = JSON.stringify(house);
		} catch (e) {
			houseSaveError = e.message;
		} finally {
			houseSaveLoading = false;
		}
	}

	function stripComputed(obj) {
		if (Array.isArray(obj)) return obj.map(stripComputed);
		if (obj && typeof obj === 'object') {
			const out = {};
			for (const [k, v] of Object.entries(obj)) {
				if (!k.startsWith('_')) out[k] = stripComputed(v);
			}
			return out;
		}
		return obj;
	}

	async function deleteHouse() {
		if (!houseName) return;
		try {
			const res = await fetch(`${API}/houses/${houseName}`, { method: 'DELETE' });
			if (!res.ok) {
				const d = await res.json().catch(() => ({}));
				throw new Error(d.detail ?? res.statusText);
			}
			houseName = null;
			house = null;
			selectedStudyId = null;
			atomicModel = null;
			activeSection = 'houses';
			await loadHousesList();
		} catch (e) {
			alert(`Failed to delete house: ${e.message}`);
		}
	}

	async function createNewHouse() {
		try {
			const res = await fetch(`${API}/houses`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					label: 'New house',
					schema_version: '0.3',
					rooms: [],
					elements: [],
					studies: [],
				}),
			});
			if (!res.ok) {
				const d = await res.json().catch(() => ({}));
				throw new Error(d.detail ?? res.statusText);
			}
			const data = await res.json();
			await loadHousesList();
			await openHouse(data.name);
		} catch (e) {
			alert(`Failed to create house: ${e.message}`);
		}
	}

	let customMaterials  = $state({});
	let customConstants  = $state({});

	// ── studies (embedded in house) ───────────────────────────────────────────
	const studies = $derived(house?.studies ?? []);

	// ── atomic model (house-level, derived from expand) ─────────────────────
	let atomicModel = $state(null);
	let atomicModelLoading = $state(false);
	let atomicModelError = $state(null);

	async function loadAtomicModel() {
		if (!houseName) { atomicModel = null; return; }
		atomicModelLoading = true;
		atomicModelError = null;
		try {
			const res = await fetch(`${API}/houses/${houseName}/expand`, { method: 'POST' });
			if (res.ok) {
				atomicModel = (await res.json()).model;
			} else {
				const body = await res.json().catch(() => ({}));
				atomicModelError = body.detail ?? `expand failed (${res.status})`;
			}
		} catch (e) {
			atomicModelError = e.message;
		} finally {
			atomicModelLoading = false;
		}
	}

	// B — debounced auto-refresh when house state changes
	let _atomicModelDebounceTimer = null;
	$effect(() => {
		JSON.stringify(house); // track house deeply
		if (_atomicModelDebounceTimer) clearTimeout(_atomicModelDebounceTimer);
		_atomicModelDebounceTimer = setTimeout(() => { loadAtomicModel(); }, 500);
	});

	// ── current study state ───────────────────────────────────────────────────
	let selectedStudyId  = $state(null);
	let simInputs        = $state({});
	let simRange         = $state({ start: '', end: '' });
	let simSolver        = $state('zoh');
	let simObservations  = $state({});
	let simInitState     = $state({ mode: 'auto', T: 20 }); // mode: 'auto' | 'uniform'

	const selectedStudy = $derived(studies.find((s) => s.id === selectedStudyId));

	// ── stale / dirty tracking ────────────────────────────────────────────────
	let lastSavedSnapshot = $state(null);
	let lastRunSnapshot   = $state(null);

	function studySnapshot() {
		return JSON.stringify({ inputs: simInputs, observations: simObservations, start: simRange.start, end: simRange.end, solver: simSolver, initial_state: simInitState });
	}

	const studyDirty = $derived(lastSavedSnapshot !== null && studySnapshot() !== lastSavedSnapshot);
	const simStale   = $derived(lastRunSnapshot !== null && studySnapshot() !== lastRunSnapshot);

	function onRunSuccess() {
		lastRunSnapshot = studySnapshot();
		loadHouse(houseName);
	}

	function loadStudyIntoState(study) {
		const snap       = $state.snapshot(study);
		simInputs        = snap.inputs ?? {};
		simSolver        = snap.solver ?? 'zoh';
		simObservations  = snap.observations ?? {};
		simInitState     = snap.initial_state ?? { mode: 'auto', T: 20 };

		const start = snap.start ?? '';
		const end   = snap.end   ?? '';
		if (start && end) {
			// Switch to dates mode so the duration effect doesn't clobber the range
			rangeMode = 'dates';
			simRange  = { start, end };
		} else {
			simRange = { start, end };
		}

		lastSavedSnapshot = studySnapshot();
		lastRunSnapshot   = null;
	}

	async function openStudy(studyId) {
		const study = studies.find((s) => s.id === studyId);
		if (!study) return;
		selectedStudyId = studyId;
		loadStudyIntoState(study);
		activeSection = 'house';
		simPaneTab    = 'sim';
	}

	// ── save study ────────────────────────────────────────────────────────────
	let saveLoading = $state(false);
	let saveError   = $state(null);

	async function saveStudy() {
		if (!houseName || !selectedStudyId) return;
		saveLoading = true;
		saveError   = null;
		const studyPayload = {
			id:            selectedStudyId,
			label:         selectedStudy?.label ?? selectedStudyId,
			type:          selectedStudy?.type ?? 'run',
			start:         simRange.start,
			end:           simRange.end,
			inputs:        simInputs,
			observations:  simObservations,
			solver:        simSolver,
			initial_state: simInitState,
		};
		// Preserve run/fit records from existing study
		if (selectedStudy?.run) studyPayload.run = selectedStudy.run;
		if (selectedStudy?.fit) studyPayload.fit = selectedStudy.fit;
		try {
			const res = await fetch(`${API}/houses/${houseName}/studies/${selectedStudyId}`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(studyPayload),
			});
			if (!res.ok) {
				const d = await res.json().catch(() => ({}));
				throw new Error(d.detail ?? res.statusText);
			}
			lastSavedSnapshot = studySnapshot();
			await loadHouse(houseName);
		} catch (e) {
			saveError = e.message;
		} finally {
			saveLoading = false;
		}
	}

	// ── simulation pane (house view) ─────────────────────────────────────────
	let simPaneTab    = $state('rc'); // 'rc' | 'studies' | 'sim'
	let rangeMode     = $state('duration'); // 'dates' | 'duration'
	let triggerRun    = $state(/** @type {(() => void) | null} */ (null));
	let durationDays  = $state(7);
	let durationStart = $state('');

	// ── create study from house ───────────────────────────────────────────────
	let createStudyLoading = $state(false);
	let createStudyError   = $state(null);

	async function createStudy(type = 'run') {
		if (!houseName) return;
		createStudyLoading = true;
		createStudyError   = null;
		try {
			const res = await fetch(`${API}/houses/${houseName}/studies`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ label: '', type }),
			});
			if (!res.ok) {
				const d = await res.json().catch(() => ({}));
				throw new Error(d.detail ?? res.statusText);
			}
			const data = await res.json();
			await loadHouse(houseName);
			await openStudy(data.id);
			simPaneTab = 'sim';
		} catch (e) {
			createStudyError = e.message;
		} finally {
			createStudyLoading = false;
		}
	}

	async function deleteStudy(studyId) {
		if (!houseName) return;
		if (!confirm('Delete this study?')) return;
		try {
			const res = await fetch(`${API}/houses/${houseName}/studies/${studyId}`, { method: 'DELETE' });
			if (!res.ok) {
				const d = await res.json().catch(() => ({}));
				throw new Error(d.detail ?? res.statusText);
			}
			if (selectedStudyId === studyId) {
				selectedStudyId = null;
				simPaneTab = 'studies';
			}
			await loadHouse(houseName);
		} catch (e) {
			alert(`Failed to delete study: ${e.message}`);
		}
	}

	onMount(async () => {
		await loadHousesList();
	});
</script>



<!-- ── shell ─────────────────────────────────────────────────────────────── -->
<div class="shell">

	<!-- left nav -->
	<nav class="sidenav">
		<div class="nav-top">
			<div class="nav-logo">miniha</div>

			<!-- top-level sections -->
			<button class="nav-item" class:active={activeSection === 'materials'} onclick={() => (activeSection = 'materials')}>
				Materials
			</button>
			<button class="nav-item" class:active={activeSection === 'houses' || activeSection === 'house'} onclick={() => (activeSection = houseName ? 'house' : 'houses')}>
				House
			</button>

			<!-- house sub-nav -->
			{#if activeSection === 'house' && houseName}
				<div class="nav-divider"></div>
				<button class="nav-item nav-back" onclick={() => { houseName = null; house = null; selectedStudyId = null; atomicModel = null; activeSection = 'houses'; }}>← all houses</button>
			{/if}
		</div>
		<div class="nav-bottom">
			<a class="nav-link" href="/docs" target="_blank" rel="noopener">API docs ↗</a>
		</div>
	</nav>

	<!-- main area -->
	<div class="main">

		{#if activeSection === 'materials'}
			<div class="body">
				<MaterialsPanel
					materials={customMaterials}
					{customConstants}
					onchange={(m) => (customMaterials = m)}
					onconstants={(c) => (customConstants = c)}
				/>
			</div>

		{:else if activeSection === 'houses'}
			<!-- ── house picker ── -->
			<div class="home">
				<div class="home-header">
					{#if housesError}
						<span class="api-warn">⚠ API unreachable — {housesError}</span>
					{:else}
						<span class="home-title">Houses</span>
					{/if}
					<button class="home-new-btn" onclick={createNewHouse}>+ New house</button>
				</div>

				<div class="house-grid">
					{#each housesList as h}
						<div class="house-card" class:selected={h.name === houseName}>
							<button class="card-open" onclick={() => openHouse(h.name)}>
								<div class="card-label">{h.label ?? h.name}</div>
								<div class="card-name">{h.name}</div>
								<div class="card-meta">
									<span>{h.n_rooms} room{h.n_rooms !== 1 ? 's' : ''}</span>
									<span>·</span>
									<span>{h.n_elements} element{h.n_elements !== 1 ? 's' : ''}</span>
									<span>·</span>
									<span>{h.n_studies} stud{h.n_studies !== 1 ? 'ies' : 'y'}</span>
								</div>
								<div class="card-hash"># {h.model_hash}</div>
							</button>
						</div>
					{/each}

					{#if housesList.length === 0 && !housesError}
						<div class="card-empty">
							<span>No houses yet.<br/>Click "+ New house" to create one.</span>
						</div>
					{/if}
				</div>
			</div>

		{:else if activeSection === 'house' && house}
			<div class="house-split">
				<div class="house-pane">
					<HousePanel
						{house}
						onchange={(h) => (house = { ...h, _model_hash: house._model_hash, studies: $state.snapshot(house.studies) })}
						{customMaterials}
						{atomicModel}
						dirty={houseDirty}
						saveLoading={houseSaveLoading}
						saveError={houseSaveError}
						onsave={saveHouse}
						ondelete={deleteHouse}
					/>
				</div>
				<div class="study-pane">
					<div class="study-pane-tabs">
						<button class="sim-tab" class:active={simPaneTab === 'rc'}         onclick={() => { simPaneTab = 'rc'; loadAtomicModel(); }}>RC Graph</button>
						<button class="sim-tab" class:active={simPaneTab === 'studies'}    onclick={() => (simPaneTab = 'studies')}>Studies</button>
						<button class="sim-tab" class:active={simPaneTab === 'sim'}
							class:disabled={!selectedStudyId}
							onclick={() => { if (selectedStudyId) simPaneTab = 'sim'; }}
						>Simulation</button>
					</div>

					{#if simPaneTab === 'rc'}
						{#if atomicModel}
							<div class="sim-pane-body">
								<div class="rc-graph-toolbar">
									<button class="rc-refresh-btn" onclick={loadAtomicModel} disabled={atomicModelLoading} title="Refresh RC graph">
										{atomicModelLoading ? '…' : '⟳'}
									</button>
								</div>
								<GraphView model={atomicModel} selected={null} onselect={() => {}} onaddedge={() => {}} groups={[]} />
							</div>
						{:else}
							<div class="study-pane-empty">
								{#if atomicModelError}
									<span class="rc-model-error">{atomicModelError}</span>
								{:else}
									<span>no atomic model</span>
								{/if}
								<button class="rc-refresh-btn" onclick={loadAtomicModel} disabled={atomicModelLoading}>
									{atomicModelLoading ? 'loading…' : '⟳ refresh'}
								</button>
							</div>
						{/if}

					{:else if simPaneTab === 'studies'}
						<div class="studies-tab-content">
							<div class="studies-tab-header">
								{#if createStudyError}<div class="home-error">{createStudyError}</div>{/if}
								<!-- new study picker -->
								<div class="new-study-wrap">
									<button class="home-new-btn" onclick={() => createStudy('run')} disabled={createStudyLoading}>
										{createStudyLoading ? 'Creating…' : '+ Run'}
									</button>
									<button class="home-new-btn home-new-fit" onclick={() => createStudy('fit')} disabled={createStudyLoading}>
										+ Fit
									</button>
								</div>
							</div>

							{#if studies.length === 0}
								<div class="studies-empty">No studies yet. Click "+ Run" or "+ Fit" to create one.</div>
							{:else}
								<table class="studies-table">
									<thead>
										<tr>
											<th>Label</th>
											<th>Start</th>
											<th>End</th>
											<th>Type</th>
											<th>Status</th>
											<th></th>
										</tr>
									</thead>
									<tbody>
										{#each studies as s}
											<tr class="study-row" class:selected-row={s.id === selectedStudyId}
												onclick={() => { openStudy(s.id); simPaneTab = 'sim'; }}>
												<td class="col-label">{s.label || s.id.slice(0, 8)}</td>
												<td class="col-date">{s.date_range?.[0] ?? s.start ?? '—'}</td>
												<td class="col-date">{s.date_range?.[1] ?? s.end ?? '—'}</td>
												<td class="col-type">
													<span class="type-badge type-{s.type ?? 'run'}">{s.type ?? 'run'}</span>
												</td>
												<td class="col-status">
													{#if s._stale_run || s._stale_fit}
														<span class="stale-badge">⚠ stale</span>
													{:else if s.run || s.fit}
														<span class="done-badge">✓</span>
													{/if}
												</td>
												<td class="col-actions" onclick={(e) => e.stopPropagation()}>
													<button class="card-action card-action-del" onclick={() => deleteStudy(s.id)} title="Delete">✕</button>
												</td>
											</tr>
										{/each}
									</tbody>
								</table>
							{/if}
						</div>

					{:else if simPaneTab === 'sim'}
						{#if !selectedStudyId}
							<div class="study-pane-empty"><span>select a study first</span></div>
						{:else if createStudyLoading}
							<div class="study-pane-empty"><span>creating…</span></div>
						{:else if createStudyError}
							<div class="study-pane-empty study-pane-error"><span>{createStudyError}</span></div>
						{:else}
							<!-- ── study header bar ── -->
							<div class="study-save-bar">
								<button class="study-back-btn" onclick={() => { selectedStudyId = null; simPaneTab = 'studies'; }}>← studies</button>
								<span class="study-save-label">{selectedStudy?.label ?? selectedStudyId}</span>
								<span class="type-badge type-{selectedStudy?.type ?? 'run'} badge-sm">{selectedStudy?.type ?? 'run'}</span>
								<button class="study-save-btn" class:dirty={studyDirty} onclick={saveStudy} disabled={saveLoading}>
									{saveLoading ? 'Saving…' : studyDirty ? 'Save ●' : 'Saved'}
								</button>
								{#if saveError}<span class="study-save-error">{saveError}</span>{/if}
							</div>

							<!-- ── control bar ── -->
							<div class="sim-controls">
								<div class="sim-ctrl-row sim-ctrl-range">
									<RangeSelect
										bind:range={simRange}
										bind:rangeMode
										bind:durationDays
										bind:durationStart
									/>
								</div>

								<div class="sim-ctrl-row sim-ctrl-initstate">
									<span class="ctrl-label">T₀</span>
									<label class="ctrl-radio">
										<input type="radio" bind:group={simInitState.mode} value="auto" />
										<span>auto</span>
									</label>
									<label class="ctrl-radio">
										<input type="radio" bind:group={simInitState.mode} value="uniform" />
										<span>uniform</span>
									</label>
									{#if simInitState.mode === 'uniform'}
										<input
											class="ctrl-number"
											type="number"
											step="0.5"
											value={simInitState.T}
											oninput={(e) => (simInitState = { ...simInitState, T: parseFloat(e.currentTarget.value) })}
											title="Initial temperature [°C]"
										/>
										<span class="ctrl-unit">°C</span>
									{/if}
								</div>

								{#if (selectedStudy?.type ?? 'run') === 'run'}
								<div class="sim-ctrl-row">
									<label class="ctrl-radio"><input type="radio" bind:group={simSolver} value="ivp" /><span>IVP (BDF)</span></label>
									<label class="ctrl-radio"><input type="radio" bind:group={simSolver} value="zoh" /><span>ZOH</span></label>
								</div>
								{/if}

								<div class="sim-ctrl-row">
									{#if (selectedStudy?.type ?? 'run') === 'run'}
										<button class="ctrl-btn ctrl-btn-run" onclick={() => triggerRun?.()}>Run</button>
									{:else}
										<button class="ctrl-btn ctrl-btn-fit" onclick={() => triggerRun?.()}>Fit</button>
									{/if}
								</div>
							</div>

							<div class="sim-pane-body scrollable">
								{#if (selectedStudy?.type ?? 'run') === 'run'}
									<SimulationRun
										house_name={houseName}
										study_id={selectedStudyId}
										inputs={simInputs}
										range={simRange}
										observations={simObservations}
										bind:solver={simSolver}
										y0_uniform={simInitState.mode === 'uniform' ? simInitState.T : null}
										{simStale}
										{onRunSuccess}
										hideControls={true}
										onready={(fn) => (triggerRun = fn)}
									/>
								{:else}
									<FitPanel
										house_name={houseName}
										study_id={selectedStudyId}
										inputs={simInputs}
										range={simRange}
										observations={simObservations}
										y0_uniform={simInitState.mode === 'uniform' ? simInitState.T : null}
										onready={(fn) => (triggerRun = fn)}
									/>
								{/if}
							</div>
						{/if}
					{/if}
				</div>
			</div>

		{/if}

	</div>
</div>

<style>
.shell {
		display: flex;
		height: 100vh;
		overflow: hidden;
	}

	/* ── side nav ── */
	.sidenav {
		width: 176px;
		flex-shrink: 0;
		background: #1e293b;
		border-right: 1px solid #334155;
		display: flex;
		flex-direction: column;
		padding: 0;
		overflow: hidden;
	}

	.nav-top {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 12px 0 8px;
		overflow-y: auto;
		overflow-x: hidden;
	}

	.nav-bottom {
		padding: 8px 10px 12px;
		border-top: 1px solid #334155;
		flex-shrink: 0;
	}

	.nav-link {
		display: block;
		color: #64748b;
		font-size: 12px;
		text-decoration: none;
		padding: 4px 6px;
		border-radius: 4px;
	}

	.nav-link:hover { color: #94a3b8; background: #1e3a5f22; }

	.nav-logo {
		color: #94a3b8;
		font-size: 12px;
		font-weight: 700;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		padding: 4px 16px 14px;
	}

	.nav-item {
		background: none;
		border: none;
		color: #94a3b8;
		font-size: 13px;
		text-align: left;
		padding: 7px 16px;
		cursor: pointer;
		transition: background 0.1s, color 0.1s;
		border-radius: 0;
	}
	.nav-item:hover  { background: #334155; color: #f1f5f9; }
	.nav-item.active { background: #334155; color: #f1f5f9; font-weight: 600; }

	.nav-tab  { padding-left: 24px; font-size: 12px; }
	.nav-back { font-size: 11px; color: #475569; }
	.nav-back:hover { color: #94a3b8; }
	.nav-dev  { color: #475569; font-style: italic; }
	.nav-dev:hover  { color: #94a3b8; }
	.nav-dev.active { color: #94a3b8; font-weight: 600; }

	.nav-divider {
		height: 1px;
		background: #334155;
		margin: 8px 12px;
	}

	.nav-house-name {
		font-size: 11px;
		font-weight: 600;
		color: #e2e8f0;
		padding: 0 16px 4px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.nav-study-id {
		font-size: 10px;
		font-family: monospace;
		color: #94a3b8;
		padding: 0 16px 4px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.nav-save {
		width: 100%;
		background: #1e3a5f;
		color: #93c5fd;
		border: 1px solid #1e4976;
		border-radius: 4px;
		padding: 6px 12px;
		font-size: 12px;
		font-weight: 600;
		cursor: pointer;
		text-align: center;
		transition: background 0.1s;
		box-sizing: border-box;
	}
	.nav-save:hover { background: #1e4976; }
	.nav-save.dirty { border-color: #f59e0b; color: #fcd34d; }

	.nav-save-error {
		font-size: 10px;
		color: #f87171;
		margin-bottom: 4px;
		word-break: break-word;
	}

	/* ── main area ── */
	.main {
		flex: 1;
		display: flex;
		flex-direction: column;
		min-width: 0;
		overflow: hidden;
	}

	/* ── house split view ── */
	.house-split {
		flex: 1;
		display: flex;
		min-height: 0;
		overflow: hidden;
	}

	.house-pane {
		flex: 1;
		display: flex;
		flex-direction: column;
		min-width: 0;
		overflow: hidden;
		border-right: 1px solid #1e293b;
	}

	.study-pane {
		flex: 2;
		min-width: 0;
		display: flex;
		flex-direction: column;
		min-height: 0;
		overflow: hidden;
		background: #111827;
	}

	.study-pane-empty {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 8px;
		align-items: center;
		justify-content: center;
		color: #334155;
		font-size: 12px;
	}

	.rc-graph-toolbar {
		position: absolute;
		top: 6px;
		right: 8px;
		z-index: 10;
	}

	.rc-refresh-btn {
		background: none;
		border: 1px solid #334155;
		color: #64748b;
		border-radius: 4px;
		padding: 2px 7px;
		font-size: 13px;
		cursor: pointer;
		line-height: 1.4;
	}
	.rc-refresh-btn:hover:not(:disabled) { color: #94a3b8; border-color: #475569; }
	.rc-refresh-btn:disabled { opacity: 0.4; cursor: default; }
	.rc-model-error { color: #f87171; max-width: 260px; text-align: center; }

	.study-pane-error { color: #f87171 !important; }

	.study-pane-tabs {
		display: flex;
		flex-shrink: 0;
		border-bottom: 1px solid #1e293b;
		background: #111827;
	}

	.sim-tab {
		flex: 1;
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		color: #64748b;
		font-size: 11px;
		font-weight: 500;
		padding: 7px 4px 5px;
		cursor: pointer;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		border-radius: 0;
		transition: color 0.1s, border-color 0.1s;
	}
	.sim-tab:hover  { color: #94a3b8; background: none; }
	.sim-tab.active { color: #e2e8f0; border-bottom-color: #3b82f6; }
	.sim-tab-dev    { color: #334155; font-style: italic; }
	.sim-tab-dev:hover { color: #64748b; }
	.sim-tab-dev.active { color: #94a3b8; border-bottom-color: #475569; }

	/* ── study save bar ── */
	.study-save-bar {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 5px 12px;
		border-bottom: 1px solid #1e293b;
		background: #0f172a;
		flex-shrink: 0;
	}

	.study-back-btn {
		background: none;
		border: none;
		color: #475569;
		font-size: 11px;
		padding: 2px 6px;
		cursor: pointer;
		border-radius: 3px;
		flex-shrink: 0;
	}
	.study-back-btn:hover { color: #94a3b8; background: #1e293b; }

	.study-save-label {
		flex: 1;
		font-size: 11px;
		font-weight: 600;
		color: #94a3b8;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.study-save-btn {
		background: none;
		border: 1px solid #334155;
		color: #475569;
		font-size: 11px;
		font-weight: 600;
		padding: 3px 10px;
		border-radius: 4px;
		cursor: pointer;
		flex-shrink: 0;
	}
	.study-save-btn:hover:not(:disabled) { background: #1e293b; color: #94a3b8; }
	.study-save-btn.dirty { border-color: #f59e0b; color: #fcd34d; }
	.study-save-btn:disabled { opacity: 0.4; cursor: default; }

	.study-save-error {
		font-size: 10px;
		color: #f87171;
		flex-shrink: 0;
	}

	.sim-pane-body {
		flex: 1;
		position: relative;
		display: flex;
		flex-direction: column;
		min-height: 0;
		overflow: hidden;
	}
	.sim-pane-body.scrollable { overflow-y: auto; }

	/* ── simulation control bar ── */
	.sim-controls {
		display: flex;
		flex-direction: column;
		gap: 0;
		border-bottom: 1px solid #1e293b;
		flex-shrink: 0;
		background: #111827;
	}

	.sim-ctrl-row {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 7px 12px;
		border-bottom: 1px solid #0f172a;
	}
	.sim-ctrl-row:last-child { border-bottom: none; }

	.sim-ctrl-range {
		flex-wrap: wrap;
		gap: 5px;
	}


	.ctrl-radio {
		display: flex;
		align-items: center;
		gap: 5px;
		cursor: pointer;
		margin-right: 6px;
	}
	.ctrl-radio span { font-size: 12px; color: #e2e8f0; }

	.ctrl-btn {
		font-size: 12px;
		font-weight: 600;
		padding: 5px 14px;
		border-radius: 4px;
		border: 1px solid #334155;
		background: #1e293b;
		color: #94a3b8;
		cursor: pointer;
	}
	.ctrl-btn:hover:not(:disabled) { background: #273548; color: #e2e8f0; }
	.ctrl-btn:disabled              { opacity: 0.35; cursor: default; }
	.ctrl-btn.active                { background: #334155; color: #e2e8f0; }

	.ctrl-btn-run {
		background: #4f46e5;
		border-color: #4338ca;
		color: #f1f5f9;
	}
	.ctrl-btn-run:hover { background: #4338ca; }

	.ctrl-btn-fit { color: #64748b; }

	.ctrl-label {
		font-size: 12px;
		color: #94a3b8;
		min-width: 20px;
	}

	.ctrl-number {
		width: 54px;
		background: #1e293b;
		border: 1px solid #334155;
		border-radius: 4px;
		color: #e2e8f0;
		font-size: 12px;
		padding: 2px 6px;
		text-align: right;
	}
	.ctrl-number:focus { outline: none; border-color: #6366f1; }

	.ctrl-unit {
		font-size: 11px;
		color: #64748b;
	}

	/* ── studies tab (right pane) ── */
	.studies-tab-content {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 14px 16px;
		overflow-y: auto;
	}

	.studies-tab-header {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 8px;
		flex-shrink: 0;
	}

	.new-study-wrap {
		display: flex;
		gap: 6px;
	}

	.home-new-fit {
		background: #14532d;
		border-color: #166534;
		color: #86efac;
	}
	.home-new-fit:hover:not(:disabled) { background: #15803d; }

	.studies-empty {
		font-size: 12px;
		color: #475569;
		padding: 24px 0;
		text-align: center;
	}

	/* ── studies table ── */
	.studies-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 12px;
	}

	.studies-table thead th {
		text-align: left;
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.07em;
		color: #475569;
		padding: 4px 10px;
		border-bottom: 1px solid #1e293b;
		font-weight: 500;
	}

	.study-row {
		cursor: pointer;
		border-bottom: 1px solid #1e293b;
		transition: background 0.1s;
	}
	.study-row:hover { background: #1e293b; }
	.study-row.selected-row { background: #1a2744; }

	.study-row td {
		padding: 7px 10px;
		color: #94a3b8;
		vertical-align: middle;
	}

	.col-label {
		color: #e2e8f0 !important;
		font-weight: 600;
		max-width: 160px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.col-date {
		font-family: monospace;
		font-size: 11px !important;
		color: #64748b !important;
		white-space: nowrap;
	}

	.col-type { width: 60px; }
	.col-status { width: 52px; }
	.col-actions { width: 36px; text-align: right; }

	.type-badge {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		padding: 2px 6px;
		border-radius: 3px;
	}
	.type-run { background: #1e3a5f; color: #93c5fd; }
	.type-fit { background: #14532d; color: #86efac; }
	.badge-sm { font-size: 9px; padding: 2px 5px; }

	.stale-badge {
		font-size: 10px;
		color: #f59e0b;
	}

	.done-badge {
		font-size: 11px;
		color: #4ade80;
	}

	/* ── disabled tab ── */
	.sim-tab.disabled {
		opacity: 0.35;
		cursor: default;
	}
	.sim-tab.disabled:hover { color: #64748b; }

	/* ── home views ── */
	.home {
		flex: 1;
		display: flex;
		flex-direction: column;
		padding: 28px 32px;
		overflow-y: auto;
		gap: 24px;
	}

	.home-header {
		display: flex;
		align-items: center;
		gap: 16px;
	}

	.home-title {
		font-size: 20px;
		font-weight: 700;
		color: #f1f5f9;
	}

	.home-new-btn {
		background: #1e3a5f;
		color: #93c5fd;
		border: 1px solid #1e4976;
		border-radius: 4px;
		padding: 5px 12px;
		font-size: 12px;
		font-weight: 600;
		cursor: pointer;
	}
	.home-new-btn:hover:not(:disabled) { background: #1e4976; }
	.home-new-btn:disabled { opacity: 0.5; cursor: default; }

	.home-error {
		font-size: 12px;
		color: #f87171;
	}

	.api-warn { font-size: 13px; color: #f59e0b; }

	/* ── house grid ── */
	.house-grid {
		display: flex;
		flex-wrap: wrap;
		gap: 12px;
	}

	.house-card {
		width: 220px;
		background: #1e293b;
		border: 1px solid #334155;
		border-radius: 8px;
		overflow: hidden;
		display: flex;
		flex-direction: column;
		transition: border-color 0.15s;
	}
	.house-card:hover { border-color: #475569; }
	.house-card.selected { border-color: #3b82f6; }

	.card-open {
		background: none;
		border: none;
		padding: 14px 14px 10px;
		text-align: left;
		cursor: pointer;
		display: flex;
		flex-direction: column;
		gap: 5px;
		flex: 1;
	}
	.card-open:hover { background: #0f172a22; }

	.card-label {
		font-size: 13px;
		font-weight: 600;
		color: #e2e8f0;
	}

	.card-name {
		font-size: 10px;
		font-family: monospace;
		color: #64748b;
	}

	.card-meta {
		display: flex;
		gap: 4px;
		font-size: 11px;
		color: #94a3b8;
		flex-wrap: wrap;
	}

	.card-hash {
		font-size: 9px;
		font-family: monospace;
		color: #475569;
	}

	.card-action {
		background: none;
		border: none;
		color: #64748b;
		font-size: 14px;
		cursor: pointer;
		padding: 2px 5px;
		border-radius: 3px;
		line-height: 1;
	}
	.card-action:hover { background: #334155; color: #f1f5f9; }
	.card-action-del:hover { background: #7f1d1d; color: #fca5a5; }

	.card-empty {
		border-style: dashed;
		padding: 20px;
		color: #94a3b8;
		font-size: 12px;
		line-height: 1.6;
		align-items: center;
		justify-content: center;
		text-align: center;
		cursor: default;
		width: auto;
		flex: 1;
		max-width: 300px;
	}

	/* ── body / content areas ── */
	.body {
		flex: 1;
		display: flex;
		min-height: 0;
	}
	.body.scrollable { overflow-y: auto; }

	.debug-view {
		flex: 1;
		overflow: auto;
		padding: 20px 24px;
	}
	.debug-view pre {
		margin: 0;
		font-family: monospace;
		font-size: 12px;
		color: #64748b;
		line-height: 1.6;
		white-space: pre-wrap;
	}

	/* ── buttons (global defaults) ── */
	button {
		background: #334155;
		color: #f1f5f9;
		border: 1px solid #475569;
		border-radius: 4px;
		padding: 4px 12px;
		font-size: 13px;
		cursor: pointer;
	}
	button:hover    { background: #475569; }
	button:disabled { opacity: 0.4; cursor: default; }
	button.primary  { background: #3b82f6; border-color: #2563eb; }
	button.primary:hover { background: #2563eb; }

	/* ── dialogs ── */
	.dialog-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0,0,0,0.6);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
	}

	.dialog {
		background: #1e293b;
		border: 1px solid #334155;
		border-radius: 8px;
		padding: 24px;
		width: 360px;
		display: flex;
		flex-direction: column;
		gap: 14px;
	}

	.dialog-title {
		font-size: 15px;
		font-weight: 700;
		color: #f1f5f9;
	}

	.dialog-error { font-size: 12px; color: #f87171; }

	.dialog-actions {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
</style>
