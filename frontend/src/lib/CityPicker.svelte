<script>
  import { room } from './store.js';
  import { createEventDispatcher } from 'svelte';

  export let open = false;

  const dispatch = createEventDispatcher();

  let query = '';
  let results = [];
  let loading = false;
  let debounceTimer = null;

  $: if (query.length >= 2) {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => search(query), 300);
  } else {
    results = [];
  }

  async function search(q) {
    loading = true;
    try {
      const url = `https://api-adresse.data.gouv.fr/search/?q=${encodeURIComponent(q)}&type=municipality&limit=8`;
      const resp = await fetch(url);
      const data = await resp.json();
      results = (data.features || []).map(f => ({
        label: f.properties.label,
        city: f.properties.city || f.properties.name,
        postcode: f.properties.postcode,
        lat: f.geometry.coordinates[1],
        lon: f.geometry.coordinates[0],
      }));
    } catch {
      results = [];
    } finally {
      loading = false;
    }
  }

  function pick(r) {
    room.update(rm => ({ ...rm, latitude: r.lat, longitude: r.lon }));
    dispatch('picked');
    close();
  }

  function close() {
    open = false;
    query = '';
    results = [];
    dispatch('close');
  }
</script>

{#if open}
  <div class="modal modal-open">
    <div class="modal-box w-11/12 max-w-md flex flex-col gap-3" style="max-height:70vh">
      <h3 class="font-semibold text-sm">Search city (France)</h3>
      <!-- svelte-ignore a11y-autofocus -->
      <input
        type="text"
        placeholder="e.g. Grenoble…"
        bind:value={query}
        autofocus
        class="input input-sm input-bordered w-full"
      />
      <div class="flex flex-col gap-0.5 overflow-y-auto flex-1 min-h-0" style="max-height:45vh">
        {#if loading}
          <p class="text-xs text-base-content/40 p-2">Searching…</p>
        {:else if query.length >= 2 && results.length === 0}
          <p class="text-xs text-base-content/40 p-2">No results</p>
        {:else}
          {#each results as r}
            <button
              class="btn btn-xs btn-ghost justify-start text-left"
              on:click={() => pick(r)}
            >
              <span>{r.label}</span>
              <span class="ml-auto text-base-content/40 font-mono text-xs">{r.lat.toFixed(4)}, {r.lon.toFixed(4)}</span>
            </button>
          {/each}
        {/if}
      </div>
      <div class="modal-action mt-0">
        <button class="btn btn-xs" on:click={close}>cancel</button>
      </div>
    </div>
    <div class="modal-backdrop" on:click={close} role="button" tabindex="-1"
      on:keydown={e => e.key === 'Escape' && close()}></div>
  </div>
{/if}
