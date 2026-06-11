<script>
	/**
	 * SignalPicker — modal combobox for selecting a signal URI.
	 *
	 * Props:
	 *   value    {string}   current signal URI (two-way bindable)
	 *   signals  {string[]} full list of available signals
	 *   label    {string}   field label shown above the trigger button
	 *   placeholder {string}
	 */
	let {
		value    = $bindable(''),
		signals  = [],
		label    = '',
		placeholder = 'measurement/field?tag=val',
		onpick   = /** @type {(v: string) => void} */ (() => {}),
	} = $props();

	let open      = $state(false);
	let query     = $state('');
	let activeIdx = $state(-1);
	let inputEl   = $state(null);
	let listEl    = $state(null);

	const filtered = $derived(
		query.trim() === ''
			? signals
			: signals.filter((s) => s.toLowerCase().includes(query.toLowerCase()))
	);

	function openModal() {
		query     = '';
		activeIdx = -1;
		open      = true;
	}

	function close() { open = false; }

	function pick(sig) {
		value = sig;
		onpick(sig);
		close();
	}

	function clear() {
		value = '';
		onpick('');
	}

	function onKeydown(e) {
		if (!open) return;
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			activeIdx = Math.min(activeIdx + 1, filtered.length - 1);
			scrollActive();
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			activeIdx = Math.max(activeIdx - 1, 0);
			scrollActive();
		} else if (e.key === 'Enter') {
			e.preventDefault();
			if (activeIdx >= 0 && filtered[activeIdx]) pick(filtered[activeIdx]);
			else if (filtered.length === 1) pick(filtered[0]);
		} else if (e.key === 'Escape') {
			close();
		}
	}

	function scrollActive() {
		if (!listEl) return;
		const el = listEl.children[activeIdx];
		el?.scrollIntoView({ block: 'nearest' });
	}

	$effect(() => {
		if (open && inputEl) {
			// wait a tick for DOM to appear
			setTimeout(() => inputEl?.focus(), 0);
		}
	});

	// reset active when filter changes
	$effect(() => { filtered; activeIdx = -1; });
</script>

<!-- trigger -->
<div class="picker-wrap">
	{#if label}<span class="picker-label">{label}</span>{/if}
	<div class="picker-trigger" class:has-value={!!value}>
		<button class="trigger-btn" onclick={openModal} title={value || placeholder}>
			<span class="trigger-text">{value || placeholder}</span>
			<span class="trigger-icon">⌄</span>
		</button>
		{#if value}
			<button class="clear-btn" onclick={clear} title="Clear">×</button>
		{/if}
	</div>
</div>

<!-- modal -->
{#if open}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="backdrop" onclick={close} onkeydown={onKeydown}></div>
	<div class="modal" role="dialog" aria-modal="true">
		<div class="modal-header">
			<span class="modal-title">{label || 'Select signal'}</span>
			<button class="close-btn" onclick={close}>×</button>
		</div>
		<div class="modal-search">
			<input
				bind:this={inputEl}
				bind:value={query}
				onkeydown={onKeydown}
				placeholder="Filter…"
				class="search-input"
				autocomplete="off"
			/>
		</div>
		<ul bind:this={listEl} class="signal-list" role="listbox">
			{#each filtered as sig, i}
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<li
					role="option"
					aria-selected={value === sig}
					class:active={i === activeIdx}
					class:selected={value === sig}
					onclick={() => pick(sig)}
				>{sig}</li>
			{:else}
				<li class="empty">No signals match</li>
			{/each}
		</ul>
	</div>
{/if}

<style>
	.picker-wrap {
		display: flex;
		flex-direction: column;
		gap: 3px;
		min-width: 0;
		flex: 1;
	}

	.picker-label {
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #94a3b8;
		white-space: nowrap;
	}

	.picker-trigger {
		display: flex;
		align-items: center;
		background: #0f172a;
		border: 1px solid #334155;
		border-radius: 4px;
		overflow: hidden;
		min-width: 0;
	}
	.picker-trigger:focus-within {
		border-color: #6366f1;
	}

	.trigger-btn {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 4px;
		background: transparent;
		border: none;
		padding: 4px 6px;
		cursor: pointer;
		min-width: 0;
		text-align: left;
	}

	.trigger-text {
		font-size: 12px;
		font-family: monospace;
		color: #94a3b8;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		flex: 1;
		min-width: 0;
	}
	.has-value .trigger-text {
		color: #e2e8f0;
	}

	.trigger-icon {
		color: #475569;
		font-size: 14px;
		flex-shrink: 0;
	}

	.clear-btn {
		background: transparent;
		border: none;
		border-left: 1px solid #1e293b;
		color: #475569;
		padding: 4px 7px;
		cursor: pointer;
		font-size: 14px;
		line-height: 1;
		flex-shrink: 0;
	}
	.clear-btn:hover { color: #f87171; }

	/* ── modal ── */
	.backdrop {
		position: fixed;
		inset: 0;
		z-index: 100;
		background: rgba(0, 0, 0, 0.45);
	}

	.modal {
		position: fixed;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		z-index: 101;
		background: #1e293b;
		border: 1px solid #334155;
		border-radius: 8px;
		width: min(680px, 90vw);
		max-height: 70vh;
		display: flex;
		flex-direction: column;
		box-shadow: 0 20px 60px rgba(0,0,0,0.6);
	}

	.modal-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 12px 16px 8px;
		border-bottom: 1px solid #334155;
		flex-shrink: 0;
	}
	.modal-title {
		font-size: 13px;
		font-weight: 600;
		color: #e2e8f0;
	}
	.close-btn {
		background: transparent;
		border: none;
		color: #64748b;
		font-size: 18px;
		cursor: pointer;
		line-height: 1;
		padding: 2px 4px;
	}
	.close-btn:hover { color: #f87171; }

	.modal-search {
		padding: 10px 12px;
		flex-shrink: 0;
	}
	.search-input {
		width: 100%;
		box-sizing: border-box;
		background: #0f172a;
		border: 1px solid #334155;
		border-radius: 4px;
		color: #e2e8f0;
		font-size: 13px;
		font-family: monospace;
		padding: 6px 10px;
	}
	.search-input:focus {
		outline: none;
		border-color: #6366f1;
	}

	.signal-list {
		list-style: none;
		margin: 0;
		padding: 0 6px 8px;
		overflow-y: auto;
		flex: 1;
	}

	.signal-list li {
		padding: 7px 10px;
		border-radius: 4px;
		font-size: 12px;
		font-family: monospace;
		color: #cbd5e1;
		cursor: pointer;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.signal-list li:hover,
	.signal-list li.active  { background: #334155; color: #f1f5f9; }
	.signal-list li.selected { color: #818cf8; }
	.signal-list li.selected::before { content: '✓ '; }
	.signal-list li.empty   { color: #475569; cursor: default; font-family: sans-serif; }
</style>
