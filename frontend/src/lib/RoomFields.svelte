<script>
  import { room } from './store.js';
  import CityPicker from './CityPicker.svelte';

  let cityPickerOpen = false;

  const fields = [
    { id: 'name',          label: 'Name',            type: 'text'   },
    { id: 'floor_area_m2', label: 'Floor area (m²)', type: 'number' },
    { id: 'height_m',      label: 'Height (m)',       type: 'number' },
    { id: 'ach',           label: 'ACH (h⁻¹)',        type: 'number' },
  ];
</script>

<CityPicker bind:open={cityPickerOpen} />

<div>
  <p class="text-xs uppercase tracking-widest text-base-content/30 mb-2">Room</p>
  <div class="flex flex-col gap-1">
    {#each fields as f}
      <label class="flex items-center gap-2">
        <span class="text-xs text-base-content/50 w-28 shrink-0">{f.label}</span>
        {#if f.type === 'text'}
          <input
            type="text"
            bind:value={$room[f.id]}
            class="input input-xs input-bordered w-full"
          />
        {:else}
          <input
            type="number"
            bind:value={$room[f.id]}
            class="input input-xs input-bordered w-full"
          />
        {/if}
      </label>
    {/each}

    <!-- lat/lon with city search -->
    <div class="flex items-center gap-2">
      <span class="text-xs text-base-content/50 w-28 shrink-0">Latitude</span>
      <input
        type="number"
        bind:value={$room.latitude}
        class="input input-xs input-bordered w-full"
      />
    </div>
    <div class="flex items-center gap-2">
      <span class="text-xs text-base-content/50 w-28 shrink-0">Longitude</span>
      <input
        type="number"
        bind:value={$room.longitude}
        class="input input-xs input-bordered w-full"
      />
      <button
        class="btn btn-xs btn-ghost shrink-0"
        title="Search city"
        on:click={() => cityPickerOpen = true}
      >📍</button>
    </div>
  </div>
</div>
