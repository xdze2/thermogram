<script>
  import { allSignals, dataSources, DATA_SOURCE_DEFS } from './store.js';
  import { createEventDispatcher } from 'svelte';

  export let open = false;
  export let targetKey = null;

  const dispatch = createEventDispatcher();

  let search = '';

  $: def = DATA_SOURCE_DEFS.find(d => d.key === targetKey);
  $: filtered = $allSignals.filter(s => !search || s.toLowerCase().includes(search.toLowerCase()));

  function pick(sig) {
    dataSources.update(ds => ({ ...ds, [targetKey]: sig }));
    dispatch('picked');
    close();
  }

  function clear() {
    dataSources.update(ds => ({ ...ds, [targetKey]: null }));
    dispatch('picked');
    close();
  }

  function close() {
    open = false;
    search = '';
    dispatch('close');
  }
</script>

{#if open}
  <!-- backdrop -->
  <div class="modal modal-open">
    <div class="modal-box w-11/12 max-w-xl flex flex-col gap-3" style="max-height:80vh">
      <h3 class="font-semibold text-sm">
        Pick signal for {def?.label} — {def?.hint}
      </h3>
      <input type="text" placeholder="filter…" bind:value={search}
        class="input input-sm input-bordered w-full" />
      <div class="flex flex-col gap-0.5 overflow-y-auto flex-1 min-h-0" style="max-height:55vh">
        {#if filtered.length === 0}
          <p class="text-xs text-base-content/30 p-2">
            {$allSignals.length ? 'no match' : 'no signals available (InfluxDB unreachable?)'}
          </p>
        {:else}
          {#each filtered as sig}
            <button
              class="btn btn-xs btn-ghost justify-start font-mono text-left"
              class:btn-active={$dataSources[targetKey] === sig}
              on:click={() => pick(sig)}
            >{sig}</button>
          {/each}
        {/if}
      </div>
      <div class="modal-action mt-0">
        <button class="btn btn-xs btn-ghost text-error" on:click={clear}>clear</button>
        <button class="btn btn-xs" on:click={close}>cancel</button>
      </div>
    </div>
    <!-- backdrop close -->
    <div class="modal-backdrop" on:click={close} role="button" tabindex="-1"
      on:keydown={e => e.key === 'Escape' && close()}></div>
  </div>
{/if}
