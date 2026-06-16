<script>
	import { onMount } from 'svelte';
	import GraphView from '$lib/GraphView.svelte';
	import LumpedView from '$lib/LumpedView.svelte';
	import FitPanel from '$lib/FitPanel.svelte';
	import HousePanel from '$lib/HousePanel.svelte';
	import MaterialsPanel from '$lib/MaterialsPanel.svelte';
	import RangeSelect from '$lib/RangeSelect.svelte';
	import SimCharts from '$lib/SimCharts.svelte';

	const API = '';

	// ── navigation ────────────────────────────────────────────────────────────
	// activeSection: 'materials' | 'houses' | 'house'
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

	function clickOutsideStudyPicker(node) {
		const handler = (e) => { if (!node.contains(e.target)) studyPickerOpen = false; };
		document.addEventListener('mousedown', handler, true);
		return { destroy() { document.removeEventListener('mousedown', handler, true); } };
	}

	// ── house-view layout state ──────────────────────────────────────────────
	let studyPickerOpen = $state(false);  // top-bar study switcher dropdown
	let showAtomicMesh  = $state(false);  // modal: raw expand() dagre graph instead of lumped cards
	let rangeMode       = $state('duration'); // 'dates' | 'duration'
	let durationDays    = $state(7);
	let durationStart   = $state('');

	// Cross-link selection shared between HousePanel (left) and LumpedView (center):
	// a house-element uuid, or null. See docs/todo_2.md "Cross-linking, left ↔ center".
	let selectedElementId = $state(null);

	// View + run/fit result state, lifted out of FitPanel so the right column's
	// SimCharts can render it (FitPanel keeps the run/fit controls + reports
	// results upward via onResult; LumpedView keeps the view via onview).
	let lumpedView      = $state(null);
	let lumpedViewToken  = $state(0); // bump to force LumpedView to reload (e.g. after a fit persists posteriors)
	let runResult        = $state({ simResult: null, fitResult: null, inputSeries: null, obsSeries: null, runError: null });

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
			studyPickerOpen = false;
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
			if (selectedStudyId === studyId) selectedStudyId = null;
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
			<!-- ── top bar ── -->
			<div class="house-topbar">
				<span class="topbar-house-name">{house.label || houseName}</span>

				<div class="study-picker-wrap" use:clickOutsideStudyPicker>
					<button class="study-picker-trigger" onclick={() => (studyPickerOpen = !studyPickerOpen)}>
						<span class="study-picker-icon">study:</span>
						<span class="study-picker-label">{selectedStudy?.label || selectedStudy?.id?.slice(0, 8) || 'none selected'}</span>
						<span class="tb-caret">{studyPickerOpen ? '▴' : '▾'}</span>
					</button>
					{#if studyPickerOpen}
						<div class="study-picker-dropdown">
							{#if createStudyError}<div class="home-error">{createStudyError}</div>{/if}
							<button class="study-picker-new" onclick={() => createStudy()} disabled={createStudyLoading}>
								{createStudyLoading ? 'Creating…' : '+ New study'}
							</button>
							{#if studies.length === 0}
								<div class="studies-empty">No studies yet.</div>
							{:else}
								{#each studies as s}
									<div class="study-picker-row" class:selected-row={s.id === selectedStudyId}
										onclick={() => { openStudy(s.id); studyPickerOpen = false; }}>
										<span class="col-label">{s.label || s.id.slice(0, 8)}</span>
										<span class="col-date">{s.date_range?.[0] ?? s.start ?? '—'} → {s.date_range?.[1] ?? s.end ?? '—'}</span>
										{#if s._stale_run || s._stale_fit}
											<span class="stale-badge">⚠ stale</span>
										{:else if s.run || s.fit}
											<span class="done-badge">✓</span>
										{/if}
										<button class="card-action card-action-del" onclick={(e) => { e.stopPropagation(); deleteStudy(s.id); }} title="Delete">✕</button>
									</div>
								{/each}
							{/if}
						</div>
					{/if}
				</div>

				{#if selectedStudyId}
					<button class="study-save-btn" class:dirty={studyDirty} onclick={saveStudy} disabled={saveLoading}>
						{saveLoading ? 'Saving…' : studyDirty ? 'Save study ●' : 'Study saved'}
					</button>
					{#if saveError}<span class="study-save-error">{saveError}</span>{/if}
				{/if}

				<button class="topbar-back" onclick={() => { houseName = null; house = null; selectedStudyId = null; atomicModel = null; activeSection = 'houses'; }}>← all houses</button>
			</div>

			<!-- ── three columns ── -->
			<div class="house-columns">

				<!-- LEFT: elements -->
				<div class="col col-elements">
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
						selectedId={selectedElementId}
						onselect={(id) => (selectedElementId = id)}
					/>
				</div>

				<!-- CENTER: lumped view + run/fit controls -->
				<div class="col col-lumped">
					{#if !selectedStudyId}
						<div class="study-pane-empty"><span>Select or create a study above.</span></div>
					{:else}
						<div class="lumped-col-toolbar">
							<button class="rc-refresh-btn" onclick={() => { showAtomicMesh = true; loadAtomicModel(); }} title="Show raw atomic expand() graph">debug: atomic mesh</button>
						</div>
						<div class="lumped-col-cards">
							<LumpedView
								house_name={houseName}
								study_id={selectedStudyId}
								selectedId={selectedElementId}
								onselect={(id) => (selectedElementId = id)}
								onview={(v) => (lumpedView = v)}
								refreshToken={lumpedViewToken}
							/>
						</div>
						<div class="lumped-col-fit">
							<FitPanel
								house_name={houseName}
								study_id={selectedStudyId}
								inputs={simInputs}
								range={simRange}
								observations={simObservations}
								solver={simSolver}
								y0_uniform={simInitState.mode === 'uniform' ? simInitState.T : null}
								view={lumpedView}
								{onRunSuccess}
								onViewRefresh={() => (lumpedViewToken += 1)}
								onResult={(r) => (runResult = r)}
							/>
						</div>
					{/if}
				</div>

				<!-- RIGHT: time range + graphs -->
				<div class="col col-right">
					<div class="range-col-block">
						<div class="range-col-row">
							<RangeSelect
								bind:range={simRange}
								bind:rangeMode
								bind:durationDays
								bind:durationStart
							/>
						</div>
						<div class="range-col-row">
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
							<label class="ctrl-radio" title="Solver for the forward run" style="margin-left:auto">
								<input type="radio" bind:group={simSolver} value="ivp" /><span>IVP</span>
							</label>
							<label class="ctrl-radio">
								<input type="radio" bind:group={simSolver} value="zoh" /><span>ZOH</span>
							</label>
						</div>
					</div>

					<div class="graphs-col">
						{#if runResult.simResult}
							<SimCharts simResult={runResult.simResult} inputSeries={runResult.inputSeries} obsSeries={runResult.obsSeries} />
						{:else}
							<div class="study-pane-empty"><span>Run a forward simulation or a fit to see graphs here.</span></div>
						{/if}
					</div>
				</div>

			</div>

			<!-- ── atomic mesh debug modal ── -->
			{#if showAtomicMesh}
				<div class="modal-backdrop" onclick={() => (showAtomicMesh = false)}>
					<div class="modal-atomic" onclick={(e) => e.stopPropagation()}>
						<div class="modal-atomic-toolbar">
							<span class="modal-atomic-title">debug: atomic mesh</span>
							<button class="rc-refresh-btn" onclick={loadAtomicModel} disabled={atomicModelLoading} title="Refresh">
								{atomicModelLoading ? '…' : '⟳'}
							</button>
							<button class="rc-refresh-btn" onclick={() => (showAtomicMesh = false)}>✕ close</button>
						</div>
						{#if atomicModel}
							<GraphView model={atomicModel} selected={null} onselect={() => {}} onaddedge={() => {}} groups={[]} />
						{:else}
							<div class="study-pane-empty">
								{#if atomicModelError}
									<span class="rc-model-error">{atomicModelError}</span>
								{:else}
									<span>no atomic model</span>
								{/if}
							</div>
						{/if}
					</div>
				</div>
			{/if}

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
	.nav-dev  { color: #475569; font-style: italic; }
	.nav-dev:hover  { color: #94a3b8; }
	.nav-dev.active { color: #94a3b8; font-weight: 600; }

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
	/* ── house top bar ── */
	.house-topbar {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 16px;
		border-bottom: 1px solid #1e293b;
		background: #0f172a;
		flex-shrink: 0;
	}

	.topbar-house-name {
		font-size: 13px;
		font-weight: 700;
		color: #f1f5f9;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 240px;
	}

	.topbar-back {
		margin-left: auto;
		background: none;
		border: none;
		color: #475569;
		font-size: 11px;
		padding: 2px 6px;
		cursor: pointer;
		border-radius: 3px;
		flex-shrink: 0;
	}
	.topbar-back:hover { color: #94a3b8; background: #1e293b; }

	/* ── study picker dropdown ── */
	.study-picker-wrap {
		position: relative;
	}

	.study-picker-trigger {
		display: flex;
		align-items: center;
		gap: 6px;
		background: #1e293b;
		border: 1px solid #334155;
		color: #cbd5e1;
		font-size: 12px;
		padding: 4px 10px;
		border-radius: 5px;
		cursor: pointer;
	}
	.study-picker-trigger:hover { background: #273548; }
	.study-picker-icon { color: #64748b; font-size: 11px; }
	.study-picker-label {
		font-weight: 600; max-width: 220px;
		overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
	}
	.tb-caret { font-size: 9px; color: #64748b; }

	.study-picker-dropdown {
		position: absolute;
		top: calc(100% + 4px);
		left: 0;
		z-index: 100;
		background: #1e293b;
		border: 1px solid #334155;
		border-radius: 6px;
		padding: 6px;
		min-width: 360px;
		max-height: 320px;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 2px;
		box-shadow: 0 4px 16px rgba(0,0,0,0.4);
	}

	.study-picker-new {
		align-self: flex-start;
		margin-bottom: 4px;
	}

	.studies-empty {
		font-size: 12px;
		color: #475569;
		padding: 10px 6px;
		text-align: center;
	}

	.study-picker-row {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 6px 8px;
		border-radius: 4px;
		cursor: pointer;
	}
	.study-picker-row:hover { background: #273548; }
	.study-picker-row.selected-row { background: #1a2744; }

	.col-label {
		color: #e2e8f0;
		font-weight: 600;
		max-width: 140px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.col-date {
		font-family: monospace;
		font-size: 11px;
		color: #64748b;
		white-space: nowrap;
		margin-left: auto;
	}

	.stale-badge { font-size: 10px; color: #f59e0b; }
	.done-badge  { font-size: 11px; color: #4ade80; }

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

	/* ── three-column layout ── */
	.house-columns {
		flex: 1;
		display: flex;
		min-height: 0;
		overflow: hidden;
	}

	.col {
		display: flex;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
		overflow: hidden;
		border-right: 1px solid #1e293b;
	}
	.col:last-child { border-right: none; }

	.col-elements { flex: 1.1; }
	.col-lumped   { flex: 1.4; background: #111827; position: relative; }
	.col-right    { flex: 1.1; background: #0b1220; }

	.study-pane-empty {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 8px;
		align-items: center;
		justify-content: center;
		color: #334155;
		font-size: 12px;
		text-align: center;
		padding: 16px;
	}

	.lumped-col-toolbar {
		position: absolute;
		top: 6px;
		right: 8px;
		z-index: 10;
	}

	.lumped-col-cards {
		flex: 1;
		min-height: 0;
		overflow: hidden;
		display: flex;
		flex-direction: column;
	}

	.lumped-col-fit {
		flex-shrink: 0;
		max-height: 45%;
		display: flex;
		flex-direction: column;
		border-top: 1px solid #1e293b;
		min-height: 0;
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

	/* ── right column: range + graphs ── */
	.range-col-block {
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
		gap: 0;
		border-bottom: 1px solid #1e293b;
		background: #111827;
	}

	.range-col-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 6px;
		padding: 7px 12px;
		border-bottom: 1px solid #0f172a;
	}
	.range-col-row:last-child { border-bottom: none; }

	.ctrl-radio {
		display: flex;
		align-items: center;
		gap: 5px;
		cursor: pointer;
		margin-right: 6px;
	}
	.ctrl-radio span { font-size: 12px; color: #e2e8f0; }

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

	.graphs-col {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
	}

	/* ── atomic mesh debug modal ── */
	.modal-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0,0,0,0.6);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 200;
	}

	.modal-atomic {
		width: 90vw;
		height: 85vh;
		background: #0f172a;
		border: 1px solid #334155;
		border-radius: 8px;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.modal-atomic-toolbar {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 12px;
		border-bottom: 1px solid #1e293b;
		flex-shrink: 0;
	}

	.modal-atomic-title {
		font-size: 12px;
		font-weight: 600;
		color: #94a3b8;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

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
