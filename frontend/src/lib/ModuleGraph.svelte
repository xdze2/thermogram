<script>
  import { assembly, roomDoc as documentStore, registry, loading, error } from '../stores/model.js';
  // assemblyStore and docStore alias the same writables — used for .set() after mutations
  import { assembly as assemblyStore, roomDoc as docStore } from '../stores/model.js';
  import {
    createModule, deleteModule, setModuleRouting,
    fetchAssembly as apiFetchAssembly,
    fetchDocument as apiFetchDocument,
  } from '../lib/api.js';
  import TopologySvg from './TopologySvg.svelte';

  // ---------------------------------------------------------------------------
  // Channels (fixed set per contract)
  // ---------------------------------------------------------------------------
  const CHANNELS = ['CONDUCTION', 'SOLAR_TRANSMISSION', 'SOLAR_OPAQUE', 'STORAGE'];

  // ---------------------------------------------------------------------------
  // Derived: ownership map keyed by (element_label, channel)
  // ---------------------------------------------------------------------------
  $: ownershipMap = buildOwnershipMap($assembly?.ownership ?? []);
  $: problemSet   = buildProblemSet($assembly?.problems ?? []);
  $: elements     = $documentStore?.elements ?? [];
  $: mods         = $documentStore?.modules ?? [];

  function buildOwnershipMap(ownership) {
    const map = {};
    for (const o of ownership) {
      map[`${o.element_label}::${o.channel}`] = o.module_id;
    }
    return map;
  }

  function buildProblemSet(problems) {
    const set = new Set();
    for (const p of problems) {
      if (p.cell) set.add(`${p.cell[0]}::${p.cell[1]}`);
    }
    return set;
  }

  // ---------------------------------------------------------------------------
  // Module lookup
  // ---------------------------------------------------------------------------
  $: moduleById = Object.fromEntries(mods.map(m => [m.id, m]));

  function moduleName(mid) {
    if (!mid) return '';
    const m = moduleById[mid];
    return m ? m.type : mid;
  }

  // ---------------------------------------------------------------------------
  // Add module
  // ---------------------------------------------------------------------------
  let addModuleType = '';
  let addModuleFields = {};
  let addModuleLoading = false;
  let addModuleError = '';

  $: if ($registry?.module_types?.length && !addModuleType) {
    addModuleType = $registry.module_types[0].type_name;
  }

  $: addModuleTypeDef = $registry?.module_types?.find(t => t.type_name === addModuleType);

  function onAddTypeChange() {
    addModuleFields = buildModuleDefaultFields(addModuleType);
  }

  function buildModuleDefaultFields(typeName) {
    const td = $registry?.module_types?.find(t => t.type_name === typeName);
    if (!td) return {};
    const out = {};
    for (const f of td.fields ?? []) {
      out[f.name] = f.default !== undefined ? f.default : '';
    }
    return out;
  }

  async function handleAddModule() {
    addModuleLoading = true;
    addModuleError = '';
    try {
      const fields = {};
      for (const [k, v] of Object.entries(addModuleFields)) {
        fields[k] = parseFloat(v) || 0;
      }
      await createModule(addModuleType, fields);
      await refreshDerived();
    } catch (err) {
      addModuleError = err.message ?? String(err);
    } finally {
      addModuleLoading = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Delete module
  // ---------------------------------------------------------------------------
  async function handleDeleteModule(mid) {
    if (!confirm(`Delete module ${moduleName(mid)}?`)) return;
    try {
      await deleteModule(mid);
      await refreshDerived();
    } catch (err) {
      alert(`Delete failed: ${err.message}`);
    }
  }

  // ---------------------------------------------------------------------------
  // Routing: toggle element membership in module
  // ---------------------------------------------------------------------------
  async function handleRoutingChange(mod, eid, checked) {
    const current = new Set(mod.element_ids ?? []);
    if (checked) {
      current.add(eid);
    } else {
      current.delete(eid);
    }
    try {
      await setModuleRouting(mod.id, [...current]);
      await refreshDerived();
    } catch (err) {
      alert(`Routing update failed: ${err.message}`);
    }
  }

  // ---------------------------------------------------------------------------
  // Refresh after mutations
  // ---------------------------------------------------------------------------
  async function refreshDerived() {
    const [asm, doc] = await Promise.all([apiFetchAssembly(), apiFetchDocument()]);
    assemblyStore.set(asm);
    docStore.set(doc);
  }

  // ---------------------------------------------------------------------------
  // Cell class helper
  // ---------------------------------------------------------------------------
  function cellClass(elemLabel, channel) {
    const key = `${elemLabel}::${channel}`;
    if (problemSet.has(key)) return 'bg-error/20 border-2 border-error';
    if (ownershipMap[key])   return 'bg-base-200';
    return '';
  }

  function cellContent(elemLabel, channel) {
    const key = `${elemLabel}::${channel}`;
    const mid = ownershipMap[key];
    if (!mid) return '—';
    return moduleName(mid);
  }
</script>

<div class="p-4 space-y-6">

  <!-- Problems banner -->
  {#if $assembly?.problems?.length}
    <div role="alert" class="alert alert-warning">
      <div>
        <div class="font-semibold mb-1">Assembly problems</div>
        {#each $assembly.problems as prob}
          <div class="text-sm">{prob.message}</div>
        {/each}
      </div>
    </div>
  {/if}

  <!-- Loading / error -->
  {#if $loading && !elements.length}
    <div class="flex justify-center py-10">
      <span class="loading loading-spinner loading-lg"></span>
    </div>
  {:else if $error}
    <div role="alert" class="alert alert-error">
      <span>{$error}</span>
    </div>
  {:else}

    <!-- ====================================================================
         Routing matrix
    ===================================================================== -->
    <section>
      <h2 class="text-xl font-semibold mb-3">Routing matrix (element × channel)</h2>
      <p class="text-sm text-base-content/60 mb-3">
        Each cell shows which module owns that (element, channel) combination.
        Red cells indicate a problem (double-count or unclaimed channel).
      </p>

      {#if elements.length === 0}
        <p class="text-base-content/60">No elements — add elements first.</p>
      {:else}
        <div class="overflow-x-auto">
          <table class="table table-sm table-bordered w-full">
            <thead>
              <tr>
                <th class="bg-base-200">Element</th>
                {#each CHANNELS as ch}
                  <th class="bg-base-200 text-xs">{ch}</th>
                {/each}
              </tr>
            </thead>
            <tbody>
              {#each elements as elem}
                <tr>
                  <td class="font-medium text-sm">{elem.label}</td>
                  {#each CHANNELS as ch}
                    {@const hasBudget = elem.budgets?.[ch] && Object.values(elem.budgets[ch]).some(v => v !== null)}
                    <td class="text-xs text-center {hasBudget ? cellClass(elem.label, ch) : 'text-base-content/20'}">
                      {#if hasBudget}
                        {cellContent(elem.label, ch)}
                        {#if problemSet.has(`${elem.label}::${ch}`)}
                          <span class="badge badge-error badge-xs ml-1">!</span>
                        {/if}
                      {:else}
                        ·
                      {/if}
                    </td>
                  {/each}
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </section>

    <!-- ====================================================================
         Star topology graph
    ===================================================================== -->
    <section>
      <h2 class="text-xl font-semibold mb-3">Topology</h2>
      <TopologySvg graph={$assembly?.graph} />
    </section>

    <!-- ====================================================================
         Module list + routing controls
    ===================================================================== -->
    <section>
      <h2 class="text-xl font-semibold mb-3">Modules</h2>

      {#if mods.length === 0}
        <p class="text-base-content/60 mb-3">No modules yet.</p>
      {:else}
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          {#each mods as mod}
            <div class="card card-border bg-base-100 shadow-sm">
              <div class="card-body p-4">
                <div class="flex items-start justify-between">
                  <div>
                    <span class="badge badge-outline badge-sm">{mod.type}</span>
                    <div class="text-xs text-base-content/50 mt-0.5">id: {mod.id}</div>
                  </div>
                  <button
                    class="btn btn-ghost btn-xs text-error"
                    onclick={() => handleDeleteModule(mod.id)}
                    aria-label="Delete module {mod.type}"
                  >
                    Remove
                  </button>
                </div>

                <!-- Element routing checkboxes -->
                {#if elements.length}
                  <div class="mt-3">
                    <div class="text-xs font-medium mb-1">Routed elements</div>
                    <div class="flex flex-col gap-1">
                      {#each elements as elem}
                        <label class="flex items-center gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            class="checkbox checkbox-sm"
                            checked={mod.element_ids?.includes(elem.id)}
                            onchange={(e) => handleRoutingChange(mod, elem.id, e.target.checked)}
                          />
                          <span class="text-sm">{elem.label}</span>
                        </label>
                      {/each}
                    </div>
                  </div>
                {/if}
              </div>
            </div>
          {/each}
        </div>
      {/if}

      <!-- Add module form -->
      <div class="card card-border bg-base-50">
        <div class="card-body p-4">
          <h3 class="font-semibold text-sm mb-2">Add module</h3>
          <div class="flex flex-wrap gap-3 items-end">
            <div class="form-control">
              <label class="label py-0" for="add-mod-type">
                <span class="label-text text-xs">Type</span>
              </label>
              <select
                id="add-mod-type"
                class="select select-bordered select-sm"
                bind:value={addModuleType}
                onchange={onAddTypeChange}
              >
                {#each $registry?.module_types ?? [] as mt}
                  <option value={mt.type_name}>{mt.type_name}</option>
                {/each}
              </select>
            </div>

            <!-- Module-type-specific fields (e.g. RoomMass needs floor_area) -->
            {#if addModuleTypeDef?.fields?.length}
              {#each addModuleTypeDef.fields as f}
                <div class="form-control">
                  <label class="label py-0" for="add-mod-{f.name}">
                    <span class="label-text text-xs">{f.name}</span>
                  </label>
                  <input
                    id="add-mod-{f.name}"
                    type="number"
                    step="any"
                    class="input input-bordered input-sm w-32"
                    bind:value={addModuleFields[f.name]}
                    placeholder={f.default !== undefined ? String(f.default) : ''}
                  />
                </div>
              {/each}
            {/if}

            <button
              class="btn btn-primary btn-sm"
              onclick={handleAddModule}
              disabled={addModuleLoading}
            >
              {#if addModuleLoading}
                <span class="loading loading-spinner loading-xs"></span>
              {/if}
              Add module
            </button>
          </div>

          {#if addModuleError}
            <div role="alert" class="alert alert-error mt-2 text-sm">
              <span>{addModuleError}</span>
            </div>
          {/if}
        </div>
      </div>
    </section>

  {/if}
</div>
