<script>
  import { schema, materials, autoName, updateElement, addLayer, removeLayer, updateLayer, removeElement } from './store.js';

  export let el;

  let open = true;

  $: displayName = el.name || autoName(el, $materials);


  function onDim(a, b) {
    const area = a * b;
    if (area > 0) updateElement(el.id, { dim_a: a, dim_b: b, area_m2: +area.toFixed(4) });
  }

  function onField(field, value) {
    updateElement(el.id, { [field]: value });
  }

  function onUOverride(e) {
    const v = e.target.value;
    updateElement(el.id, { u_value_override: v === '' ? null : parseFloat(v) });
  }

  function onLayerMaterial(idx, key) {
    updateLayer(el.id, idx, { material_key: key });
  }

  function onLayerThickness(idx, e) {
    updateLayer(el.id, idx, { thickness_m: parseFloat(e.target.value) });
  }
</script>

<div class="card card-border bg-base-200 card-compact">
  <!-- Header -->
  <div
    class="card-title px-3 py-2 cursor-pointer select-none flex justify-between items-center text-sm hover:bg-base-300 rounded-t"
    on:click={() => open = !open}
    role="button"
    tabindex="0"
    on:keydown={e => e.key === 'Enter' && (open = !open)}
  >
    <span class="font-medium text-base-content">{displayName}</span>
    <span class="text-xs text-base-content/40">{el.type} · {el.orientation} · {el.area_m2} m²</span>
  </div>

  {#if open}
    <div class="card-body pt-2">
      <!-- Main fields -->
      <div class="flex flex-col gap-1">
        <label class="flex items-center gap-2">
          <span class="text-xs text-base-content/50 w-24 shrink-0">Name</span>
          <input type="text" value={el.name ?? ''}
            placeholder={autoName(el, $materials)}
            on:input={e => onField('name', e.target.value || null)}
            class="input input-xs input-bordered w-full" />
        </label>

        <label class="flex items-center gap-2">
          <span class="text-xs text-base-content/50 w-24 shrink-0">Type</span>
          <select value={el.type}
            on:change={e => onField('type', e.target.value)}
            class="select select-xs select-bordered w-full">
            {#each $schema.element_types as t}
              <option value={t.value}>{t.label}</option>
            {/each}
          </select>
        </label>

        <label class="flex items-center gap-2">
          <span class="text-xs text-base-content/50 w-24 shrink-0">Orientation</span>
          <select value={el.orientation}
            on:change={e => onField('orientation', e.target.value)}
            class="select select-xs select-bordered w-full">
            {#each $schema.orientations as o}
              <option value={o.value}>{o.label}</option>
            {/each}
          </select>
        </label>

        <div class="flex items-center gap-2">
          <span class="text-xs text-base-content/50 w-24 shrink-0">Size (m)</span>
          <input type="number" value={el.dim_a} min="0.01" step="0.1"
            on:input={e => onDim(parseFloat(e.target.value), el.dim_b)}
            class="input input-xs input-bordered w-full" />
          <span class="text-xs text-base-content/40">×</span>
          <input type="number" value={el.dim_b} min="0.01" step="0.1"
            on:input={e => onDim(el.dim_a, parseFloat(e.target.value))}
            class="input input-xs input-bordered w-full" />
          <span class="text-xs text-base-content/30 whitespace-nowrap">{el.area_m2} m²</span>
        </div>

        <label class="flex items-center gap-2">
          <span class="text-xs text-base-content/50 w-24 shrink-0">U override</span>
          <input type="number" value={el.u_value_override ?? ''}
            placeholder="auto (W/m²K)"
            on:input={onUOverride}
            class="input input-xs input-bordered w-full" />
        </label>
      </div>

      <!-- Layers -->
      <div class="mt-3">
        <p class="text-xs uppercase tracking-widest text-base-content/30 mb-1">Layers (inside → outside)</p>
        <div class="flex flex-col gap-1">
          {#each el.layers as layer, idx}
            <div class="grid gap-1 items-center" style="grid-template-columns: 1fr 72px 24px">
              <select value={layer.material_key}
                on:change={e => onLayerMaterial(idx, e.target.value)}
                class="select select-xs select-bordered w-full">
                {#each $materials as m}
                  <option value={m.key}>{m.name}</option>
                {/each}
              </select>
              <input type="number" value={layer.thickness_m}
                on:input={e => onLayerThickness(idx, e)}
                placeholder="m"
                class="input input-xs input-bordered w-full" />
              <button class="btn btn-xs btn-ghost text-error px-1"
                on:click={() => removeLayer(el.id, idx)}>✕</button>
            </div>
          {/each}
        </div>
        <button class="btn btn-xs btn-ghost mt-1"
          on:click={() => addLayer(el.id)}>+ layer</button>
      </div>

      <button class="btn btn-xs btn-ghost text-error mt-2"
        on:click={() => removeElement(el.id)}>remove element</button>
    </div>
  {/if}
</div>
