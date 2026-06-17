<script>
  import { dataSources, DATA_SOURCE_DEFS, rangeStart, rangeEnd, addDays, todayISO } from './store.js';
  import SignalPicker from './SignalPicker.svelte';
  import { createEventDispatcher } from 'svelte';

  const dispatch = createEventDispatcher();

  let pickerOpen = false;
  let pickerTarget = null;

  function openPicker(key) {
    pickerTarget = key;
    pickerOpen = true;
  }

  function onPicked() {
    dispatch('change');
  }

  function extendEnd(days) {
    const cur = $rangeEnd || todayISO();
    rangeEnd.set(addDays(cur, days));
    dispatch('change');
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
  <div class="flex flex-col gap-1">
    <label class="flex items-center gap-2">
      <span class="text-xs text-base-content/50 w-10 shrink-0">Start</span>
      <input type="text" placeholder="YYYY-MM-DD"
        bind:value={$rangeStart}
        on:input={() => dispatch('change')}
        class="input input-xs input-bordered flex-1 font-mono" />
    </label>
    <label class="flex items-center gap-2">
      <span class="text-xs text-base-content/50 w-10 shrink-0">End</span>
      <input type="text" placeholder="YYYY-MM-DD"
        bind:value={$rangeEnd}
        on:input={() => dispatch('change')}
        class="input input-xs input-bordered flex-1 font-mono" />
    </label>
    <div class="flex gap-1 mt-0.5">
      <button class="btn btn-xs btn-ghost" on:click={() => extendEnd(7)}>+7 d</button>
      <button class="btn btn-xs btn-ghost" on:click={() => extendEnd(30)}>+30 d</button>
      <button class="btn btn-xs btn-ghost" on:click={() => extendEnd(90)}>+90 d</button>
    </div>
  </div>
</div>

<SignalPicker bind:open={pickerOpen} targetKey={pickerTarget} on:picked={onPicked} />
