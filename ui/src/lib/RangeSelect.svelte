<script>
	const DAY_PRESETS = [1, 2, 3, 5, 7, 10, 14, 21, 30, 60, 90];

	let {
		range        = $bindable({ start: '', end: '' }),
		rangeMode    = $bindable('duration'),
		durationDays = $bindable(7),
		durationStart = $bindable(''),
	} = $props();

	function isoDate(d) { return d.toISOString().slice(0, 10); }

	function applyDuration() {
		if (!durationStart) return;
		const start = new Date(durationStart + 'T00:00:00');
		const end   = new Date(start);
		end.setDate(end.getDate() + durationDays);
		range = { start: isoDate(start), end: isoDate(end) };
	}

	$effect(() => { durationDays; durationStart; applyDuration(); });
</script>

<div class="range-select">
	{#if rangeMode === 'dates'}
		<input class="ctrl-date" type="date"
			value={range.start}
			oninput={(e) => (range = { ...range, start: e.currentTarget.value })}
			title="Start"
		/>
		<span class="ctrl-range-sep">→</span>
		<input class="ctrl-date" type="date"
			value={range.end}
			oninput={(e) => (range = { ...range, end: e.currentTarget.value })}
			title="End"
		/>
		<button class="ctrl-mode-toggle" onclick={() => (rangeMode = 'duration')} title="Switch to duration mode">⇄</button>
	{:else}
		<input class="ctrl-date ctrl-date-start" type="date"
			bind:value={durationStart}
			title="Start"
		/>
		<div class="ctrl-presets">
			{#each DAY_PRESETS as d}
				<button class="ctrl-preset" class:active={durationDays === d} onclick={() => (durationDays = d)}>{d}d</button>
			{/each}
		</div>
		<input class="ctrl-date ctrl-date-end" type="date"
			value={range.end}
			readonly
			title="End (computed)"
		/>
		<button class="ctrl-mode-toggle" onclick={() => (rangeMode = 'dates')} title="Switch to start/end mode">⇄</button>
	{/if}
</div>

<style>
	.range-select {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 5px;
		flex: 1;
	}

	.ctrl-date {
		background: #0f172a;
		color: #e2e8f0;
		border: 1px solid #334155;
		border-radius: 3px;
		padding: 4px 6px;
		font-size: 12px;
		font-family: monospace;
		flex: 1;
		min-width: 110px;
		color-scheme: dark;
	}
	.ctrl-date:focus     { outline: none; border-color: #6366f1; }
	.ctrl-date[readonly] { color: #64748b; }

	.ctrl-range-sep {
		color: #475569;
		font-size: 12px;
		flex-shrink: 0;
	}

	.ctrl-presets {
		display: flex;
		flex-wrap: wrap;
		gap: 3px;
		flex: 1;
	}

	.ctrl-preset {
		background: #1e293b;
		border: 1px solid #334155;
		color: #64748b;
		font-size: 10px;
		font-family: monospace;
		padding: 3px 6px;
		border-radius: 3px;
		cursor: pointer;
		min-width: 28px;
		text-align: center;
	}
	.ctrl-preset:hover  { background: #273548; color: #94a3b8; }
	.ctrl-preset.active { background: #334155; color: #e2e8f0; border-color: #6366f1; }

	.ctrl-mode-toggle {
		background: none;
		border: 1px solid #334155;
		color: #475569;
		font-size: 13px;
		padding: 3px 7px;
		border-radius: 3px;
		cursor: pointer;
		flex-shrink: 0;
	}
	.ctrl-mode-toggle:hover { color: #94a3b8; background: #1e293b; }
</style>
