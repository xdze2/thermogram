<script>
  import {
    elements, assembly, registry, loading, error,
    addElement, editElement, removeElement,
  } from '../stores/model.js';

  // ---------------------------------------------------------------------------
  // Modal state
  // ---------------------------------------------------------------------------
  let modalOpen = false;
  let modalMode = 'add'; // 'add' | 'edit'
  let editingElement = null;  // Element object when editing

  // Form state
  let selectedType = '';
  let formFields = {};
  let formError = '';
  let formLoading = false;

  // ---------------------------------------------------------------------------
  // Derived: map from element_id -> [param names that use it]
  // ---------------------------------------------------------------------------
  $: paramsByElement = buildParamsByElement($assembly);

  function buildParamsByElement(asm) {
    const map = {};
    if (!asm?.parameters) return map;
    for (const param of asm.parameters) {
      for (const contrib of param.contributions ?? []) {
        if (!map[contrib.element_id]) map[contrib.element_id] = [];
        if (!map[contrib.element_id].includes(param.name)) {
          map[contrib.element_id].push(param.name);
        }
      }
    }
    return map;
  }

  // ---------------------------------------------------------------------------
  // Open modal helpers
  // ---------------------------------------------------------------------------
  function openAddModal() {
    modalMode = 'add';
    editingElement = null;
    selectedType = $registry?.element_types?.[0]?.type_name ?? '';
    formFields = buildDefaultFields(selectedType);
    formError = '';
    modalOpen = true;
  }

  function openEditModal(elem) {
    modalMode = 'edit';
    editingElement = elem;
    selectedType = elem.type;
    formFields = deepClone(elem.fields);
    formError = '';
    modalOpen = true;
  }

  function closeModal() {
    modalOpen = false;
    formError = '';
  }

  // ---------------------------------------------------------------------------
  // Registry helpers
  // ---------------------------------------------------------------------------
  $: currentTypeDef = $registry?.element_types?.find(t => t.type_name === selectedType);

  function buildDefaultFields(typeName) {
    const typeDef = $registry?.element_types?.find(t => t.type_name === typeName);
    if (!typeDef) return {};
    const fields = {};
    for (const field of typeDef.fields) {
      if (field.type === 'list[layer]') {
        fields[field.name] = [];
      } else if (field.default !== undefined) {
        fields[field.name] = field.default;
      } else if (field.type === 'enum') {
        fields[field.name] = field.options?.[0] ?? '';
      } else {
        fields[field.name] = '';
      }
    }
    return fields;
  }

  function onTypeChange() {
    formFields = buildDefaultFields(selectedType);
  }

  function addLayer(fieldName) {
    const layerSchema = $registry?.layer_schema;
    if (!layerSchema) return;
    const newLayer = {};
    for (const f of layerSchema.fields) {
      newLayer[f.name] = f.type === 'enum' ? f.options?.[0] ?? '' : '';
    }
    formFields = { ...formFields, [fieldName]: [...(formFields[fieldName] ?? []), newLayer] };
  }

  function removeLayer(fieldName, idx) {
    const updated = [...(formFields[fieldName] ?? [])];
    updated.splice(idx, 1);
    formFields = { ...formFields, [fieldName]: updated };
  }

  function updateLayerField(fieldName, idx, key, value) {
    const updated = [...(formFields[fieldName] ?? [])];
    updated[idx] = { ...updated[idx], [key]: value };
    formFields = { ...formFields, [fieldName]: updated };
  }

  // ---------------------------------------------------------------------------
  // Submit form
  // ---------------------------------------------------------------------------
  async function submitForm() {
    formError = '';
    formLoading = true;
    try {
      // Parse numeric fields
      const parsedFields = parseFields(currentTypeDef, formFields);

      if (modalMode === 'add') {
        await addElement(selectedType, parsedFields);
      } else {
        await editElement(editingElement.id, parsedFields);
      }
      // Stores are guaranteed fresh after the await (applyMutation invariant).
      closeModal();
    } catch (err) {
      formError = err.message ?? String(err);
    } finally {
      formLoading = false;
    }
  }

  // Parse string form values to correct JS types per schema
  function parseFields(typeDef, raw) {
    if (!typeDef) return raw;
    const out = {};
    for (const field of typeDef.fields) {
      const val = raw[field.name];
      if (field.type === 'float') {
        out[field.name] = parseFloat(val) || 0;
      } else if (field.type === 'int') {
        out[field.name] = parseInt(val, 10) || 0;
      } else if (field.type === 'list[layer]') {
        // Parse numeric fields within layers
        const layerSchema = $registry?.layer_schema;
        out[field.name] = (val ?? []).map(layer => {
          const parsedLayer = {};
          for (const lf of layerSchema?.fields ?? []) {
            const lv = layer[lf.name];
            parsedLayer[lf.name] = lf.type === 'float' ? parseFloat(lv) || 0 : lv;
          }
          return parsedLayer;
        });
      } else {
        out[field.name] = val;
      }
    }
    return out;
  }

  // ---------------------------------------------------------------------------
  // Delete element
  // ---------------------------------------------------------------------------
  async function handleDelete(eid) {
    if (!confirm('Delete this element?')) return;
    try {
      await removeElement(eid);
      // Stores are guaranteed fresh after the await (applyMutation invariant).
    } catch (err) {
      alert(`Delete failed: ${err.message}`);
    }
  }

  // ---------------------------------------------------------------------------
  // Utility
  // ---------------------------------------------------------------------------
  function deepClone(obj) {
    return JSON.parse(JSON.stringify(obj));
  }

  function formatBudget(budgets) {
    if (!budgets) return [];
    return Object.entries(budgets).map(([channel, bvals]) => {
      const nonNull = Object.entries(bvals)
        .filter(([, v]) => v !== null)
        .map(([k, v]) => `${k}: ${typeof v === 'number' ? v.toFixed(2) : v}`);
      if (!nonNull.length) return null;
      return { channel, values: nonNull.join(', ') };
    }).filter(Boolean);
  }
</script>

<div class="p-4">
  <!-- Header -->
  <div class="flex items-center justify-between mb-4">
    <h2 class="text-xl font-semibold">Building Elements</h2>
    <button class="btn btn-primary btn-sm" onclick={openAddModal}>
      + Add element
    </button>
  </div>

  <!-- Loading / error -->
  {#if $loading && !$elements.length}
    <div class="flex justify-center py-10">
      <span class="loading loading-spinner loading-lg"></span>
    </div>
  {:else if $error}
    <div role="alert" class="alert alert-error mb-4">
      <span>{$error}</span>
    </div>
  {:else if !$elements.length}
    <div class="text-center text-base-content/60 py-10">
      No elements yet. Add one to get started.
    </div>
  {:else}
    <!-- Element cards grid -->
    <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      {#each $elements as elem (elem.id)}
        <div class="card card-border bg-base-100 shadow-sm">
          <div class="card-body p-4">
            <!-- Card header -->
            <div class="flex items-start justify-between">
              <div>
                <span class="badge badge-outline badge-sm mb-1">{elem.type}</span>
                <h3 class="card-title text-base">{elem.label}</h3>
              </div>
              <div class="flex gap-1">
                <button
                  class="btn btn-ghost btn-xs"
                  aria-label="Edit {elem.label}"
                  onclick={() => openEditModal(elem)}
                >
                  Edit
                </button>
                <button
                  class="btn btn-ghost btn-xs text-error"
                  aria-label="Delete {elem.label}"
                  onclick={() => handleDelete(elem.id)}
                >
                  Delete
                </button>
              </div>
            </div>

            <!-- Key fields -->
            <div class="text-sm text-base-content/70 mt-1">
              {#each Object.entries(elem.fields) as [k, v]}
                {#if k !== 'layers'}
                  <div><span class="font-medium">{k}:</span> {v}</div>
                {/if}
              {/each}
              {#if elem.fields?.layers?.length}
                <div class="font-medium mt-1">Layers:</div>
                {#each elem.fields.layers as layer, i}
                  <div class="ml-2 text-xs">
                    {i+1}. {layer.material} {layer.thickness}m
                  </div>
                {/each}
              {/if}
            </div>

            <!-- Channel budgets -->
            {#if elem.budgets}
              <div class="divider my-1 text-xs">Channel budgets</div>
              <div class="flex flex-col gap-0.5">
                {#each formatBudget(elem.budgets) as row}
                  <div class="text-xs flex gap-2">
                    <span class="badge badge-ghost badge-xs">{row.channel}</span>
                    <span class="text-base-content/70">{row.values}</span>
                  </div>
                {/each}
              </div>
            {/if}

            <!-- Which parameters this element feeds -->
            {#if paramsByElement[elem.id]?.length}
              <div class="divider my-1 text-xs">Feeds parameters</div>
              <div class="flex flex-wrap gap-1">
                {#each paramsByElement[elem.id] as pname}
                  <span class="badge badge-primary badge-sm">{pname}</span>
                {/each}
              </div>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>

<!-- Add / Edit modal -->
{#if modalOpen}
  <dialog class="modal modal-open" aria-modal="true" aria-label="{modalMode === 'add' ? 'Add element' : 'Edit element'}">
    <div class="modal-box w-11/12 max-w-xl">
      <h3 class="font-bold text-lg mb-4">
        {modalMode === 'add' ? 'Add element' : `Edit ${editingElement?.label}`}
      </h3>

      <form onsubmit={(e) => { e.preventDefault(); submitForm(); }}>

        <!-- Type selector (only for add) -->
        {#if modalMode === 'add'}
          <div class="form-control mb-3">
            <label class="label" for="elem-type">
              <span class="label-text font-medium">Element type</span>
            </label>
            <select
              id="elem-type"
              class="select select-bordered w-full"
              bind:value={selectedType}
              onchange={onTypeChange}
            >
              {#each $registry?.element_types ?? [] as et}
                <option value={et.type_name}>{et.type_name}</option>
              {/each}
            </select>
          </div>
        {/if}

        <!-- Dynamic fields from registry -->
        {#if currentTypeDef}
          {#each currentTypeDef.fields as field}
            <div class="form-control mb-3">
              <label class="label" for="field-{field.name}">
                <span class="label-text font-medium">{field.name}</span>
              </label>

              {#if field.type === 'enum'}
                <select
                  id="field-{field.name}"
                  class="select select-bordered w-full"
                  bind:value={formFields[field.name]}
                >
                  {#each field.options ?? [] as opt}
                    <option value={opt}>{opt}</option>
                  {/each}
                </select>

              {:else if field.type === 'list[layer]'}
                <!-- Repeatable layer sub-form -->
                <div class="border border-base-300 rounded-lg p-3">
                  {#each formFields[field.name] ?? [] as layer, idx}
                    <div class="flex gap-2 items-end mb-2 flex-wrap">
                      {#each $registry?.layer_schema?.fields ?? [] as lf}
                        <div class="form-control flex-1 min-w-24">
                          <label class="label py-0" for="layer-{idx}-{lf.name}">
                            <span class="label-text text-xs">{lf.name}</span>
                          </label>
                          {#if lf.type === 'enum'}
                            <select
                              id="layer-{idx}-{lf.name}"
                              class="select select-bordered select-sm w-full"
                              value={layer[lf.name]}
                              onchange={(e) => updateLayerField(field.name, idx, lf.name, e.target.value)}
                            >
                              {#each lf.options ?? [] as opt}
                                <option value={opt}>{opt}</option>
                              {/each}
                            </select>
                          {:else}
                            <input
                              id="layer-{idx}-{lf.name}"
                              type="number"
                              step="any"
                              class="input input-bordered input-sm w-full"
                              value={layer[lf.name]}
                              oninput={(e) => updateLayerField(field.name, idx, lf.name, e.target.value)}
                            />
                          {/if}
                        </div>
                      {/each}
                      <button
                        type="button"
                        class="btn btn-ghost btn-sm text-error"
                        onclick={() => removeLayer(field.name, idx)}
                        aria-label="Remove layer {idx+1}"
                      >
                        Remove
                      </button>
                    </div>
                  {/each}
                  <button
                    type="button"
                    class="btn btn-outline btn-xs mt-1"
                    onclick={() => addLayer(field.name)}
                  >
                    + Add layer
                  </button>
                </div>

              {:else}
                <input
                  id="field-{field.name}"
                  type="number"
                  step="any"
                  class="input input-bordered w-full"
                  bind:value={formFields[field.name]}
                  placeholder={field.default !== undefined ? String(field.default) : ''}
                />
              {/if}
            </div>
          {/each}
        {/if}

        <!-- Form-level error -->
        {#if formError}
          <div role="alert" class="alert alert-error mb-3 text-sm">
            <span>{formError}</span>
          </div>
        {/if}

        <div class="modal-action">
          <button type="button" class="btn btn-ghost" onclick={closeModal}>Cancel</button>
          <button type="submit" class="btn btn-primary" disabled={formLoading}>
            {#if formLoading}
              <span class="loading loading-spinner loading-sm"></span>
            {/if}
            {modalMode === 'add' ? 'Add' : 'Save'}
          </button>
        </div>
      </form>
    </div>
    <!-- Backdrop closes modal -->
    <button class="modal-backdrop" onclick={closeModal} aria-label="Close modal"></button>
  </dialog>
{/if}
