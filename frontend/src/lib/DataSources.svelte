<script>
  import { dataSources, DATA_SOURCE_DEFS, rangeStart, rangeEnd, addDays } from './store.js';
  import SignalPicker from './SignalPicker.svelte';
  import { createEventDispatcher } from 'svelte';

  export let studyId;

  const dispatch = createEventDispatcher();

  let pickerOpen = false;
  let pickerTarget = null;
  let fetching = false;
  let fetchStatus = '';

  function openPicker(key) {
    pickerTarget = key;
    pickerOpen = true;
  }

  function onPicked() {
    dispatch('change');
  }

  const DAY_OPTIONS = [1, 2, 3, 4, 5, 10];
  let nbDays = 7;

  function setDuration(n) {
    nbDays = n;
    rangeEnd.set(addDays($rangeStart, n));
    dispatch('change');
  }

  function onStartChange() {
    rangeEnd.set(addDays($rangeStart, nbDays));
    dispatch('change');
  }

  async function fetchData() {
    fetching = true;
    fetchStatus = 'fetching…';
    try {
      const r = await fetch(`/api/studies/${studyId}/fetch_data`, { method: 'POST' });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        fetchStatus = `error: ${err.detail ?? r.statusText}`;
        return;
      }
      const data = await r.json();
      const totalPts = Object.values(data).reduce((n, pairs) => n + pairs.length, 0);
      fetchStatus = `${totalPts} pts cached`;
      dispatch('fetched', data);
    } catch (e) {
      fetchStatus = `error: ${e.message}`;
    } finally {
      fetching = false;
    }
  }
</script>

<!-- Data sources -->
<div>
  <p class="text-xs uppercase tracking-widest text-base-content/30 mb-2">Data sources</p>
  <div class="flex flex-col gap-1">
    {#each DATA_SOURCE_DEFS as def}
      <div class="flex items-center gap-2 text-xs">
        <span class="text-base-content/50 w-12 shrink-0 font-mono">{def.label}</span>
        <span class="flex-1 truncate text-base-content/40 italic"
          title={$dataSources[def.key] ?? ''}>
          {#if $dataSources[def.key]}
            {$dataSources[def.key]}
          {:else}
            <span class="text-base-content/20">{def.hint}</span>
          {/if}
        </span>
        <button class="btn btn-xs btn-ghost px-1"
          on:click={() => openPicker(def.key)}>pick</button>
      </div>
    {/each}
  </div>
</div>

<!-- Time range -->
<div>
  <p class="text-xs uppercase tracking-widest text-base-content/30 mb-2">Time range</p>
  <div class="flex flex-col gap-1.5">
    <label class="flex items-center gap-2">
      <span class="text-xs text-base-content/50 w-10 shrink-0">Start</span>
      <input type="date"
        bind:value={$rangeStart}
        on:change={onStartChange}
        class="input input-xs input-bordered flex-1 font-mono" />
    </label>
    <div class="flex items-center gap-1 flex-wrap">
      <span class="text-xs text-base-content/50 w-10 shrink-0">Days</span>
      {#each DAY_OPTIONS as n}
        <button
          class="btn btn-xs"
          class:btn-primary={nbDays === n}
          class:btn-ghost={nbDays !== n}
          on:click={() => setDuration(n)}>{n}</button>
      {/each}
    </div>
    <div class="flex items-center gap-2">
      <span class="text-xs text-base-content/50 w-10 shrink-0">End</span>
      <span class="text-xs font-mono text-base-content/40">{$rangeEnd}</span>
    </div>
  </div>
</div>

<!-- Fetch button -->
<div class="flex items-center gap-2">
  <button
    class="btn btn-xs btn-outline"
    class:loading={fetching}
    disabled={fetching}
    on:click={fetchData}
  >
    {fetching ? 'fetching…' : 'Fetch data'}
  </button>
  {#if fetchStatus}
    <span class="text-xs text-base-content/40">{fetchStatus}</span>
  {/if}
</div>

<SignalPicker bind:open={pickerOpen} targetKey={pickerTarget} on:picked={onPicked} />
