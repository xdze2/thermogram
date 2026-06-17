<script>
  import { room } from './store.js';

  const fields = [
    { id: 'name',         label: 'Name',            type: 'text'   },
    { id: 'floor_area_m2',label: 'Floor area (m²)', type: 'number' },
    { id: 'height_m',     label: 'Height (m)',       type: 'number' },
    { id: 'ach',          label: 'ACH (h⁻¹)',        type: 'number' },
    { id: 'latitude',     label: 'Latitude',         type: 'number' },
    { id: 'longitude',    label: 'Longitude',        type: 'number' },
  ];
</script>

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
  </div>
</div>
