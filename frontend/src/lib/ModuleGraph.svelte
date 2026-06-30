<script>
  import { assembly, roomDoc, registry, loading, error,
           addModule, removeModule, routeModule } from '../stores/model.js';
  import { topologySvgUrl, fetchIdentifiability } from '../lib/api.js';

  // ---------------------------------------------------------------------------
  // Channels (fixed set per contract)
  // ---------------------------------------------------------------------------
  const CHANNELS = ['CONDUCTION', 'SOLAR_TRANSMISSION', 'SOLAR_OPAQUE', 'STORAGE'];

  // ---------------------------------------------------------------------------
  // Server-rendered schematic (schemdraw busbar from draw.py via /topology.svg).
  // The endpoint serves a raster, so we cache-bust it whenever the assembly
  // changes (any mutation re-pulls $assembly per spec 10) to force a reload.
  // `svgError` toggles a fallback message when the room is too incomplete to
  // render (the endpoint 400s in that case).
  // ---------------------------------------------------------------------------
  let svgError = false;
  $: schematicUrl = $assembly
    ? `${topologySvgUrl()}?v=${assemblyVersion($assembly)}`
    : '';
  // Reset the error flag whenever we point at a fresh image.
  $: if (schematicUrl) svgError = false;

  function assemblyVersion(asm) {
    // A cheap content hash: ownership cells + problems + state/signal counts.
    // Changes on any structural edit, so the browser re-requests the image.
    const own = (asm.ownership ?? []).map(o => `${o.element_id}:${o.channel}:${o.module_id}`).join(',');
    const prob = (asm.problems ?? []).length;
    return encodeURIComponent(`${own}|${prob}`);
  }

  // ---------------------------------------------------------------------------
  // Derived: ownership map keyed by (element_label, channel)
  // ---------------------------------------------------------------------------
  $: ownershipMap = buildOwnershipMap($assembly?.ownership ?? []);
  $: problemSet   = buildProblemSet($assembly?.problems ?? []);
  $: elements     = $roomDoc?.elements ?? [];
  $: mods         = $roomDoc?.modules ?? [];

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
  // Module lookup + registry owns map
  // ---------------------------------------------------------------------------
  $: moduleById = Object.fromEntries(mods.map(m => [m.id, m]));

  /** Map from type_name -> owns[] from the registry. */
  $: moduleOwns = buildModuleOwns($registry);

  function buildModuleOwns(reg) {
    const map = {};
    for (const mt of reg?.module_types ?? []) {
      map[mt.type_name] = mt.owns ?? [];
    }
    return map;
  }

  function moduleName(mid) {
    if (!mid) return '';
    const m = moduleById[mid];
    return m ? m.type : mid;
  }

  // ---------------------------------------------------------------------------
  // Routing compatibility helpers
  // ---------------------------------------------------------------------------

  /**
   * Returns the set of channels that element `elem` actually offers a budget for.
   * A channel is "offered" when its budget object has at least one non-null field.
   */
  function offeredChannels(elem) {
    const offered = new Set();
    for (const [ch, bvals] of Object.entries(elem.budgets ?? {})) {
      if (bvals && Object.values(bvals).some(v => v !== null)) {
        offered.add(ch);
      }
    }
    return offered;
  }

  /**
   * Returns true when module `mod` can own at least one channel that `elem`
   * actually offers a budget for — i.e. m.owns ∩ elem.offeredChannels ≠ ∅.
   * RoomMass has owns=[] so this always returns false for it.
   */
  function moduleCanRouteElement(mod, elem) {
    const owns = moduleOwns[mod.type] ?? [];
    if (owns.length === 0) return false;
    const offered = offeredChannels(elem);
    return owns.some(ch => offered.has(ch));
  }

  /**
   * The channels a module would actually consume from an element: the
   * intersection of the module's owns set with the element's offered channels.
   * This is what the assembler routes — it can be a strict subset of the
   * element's channels (e.g. DirectLoss takes only CONDUCTION from a Window
   * that also offers SOLAR_TRANSMISSION). Surfaced as the per-element caption.
   */
  function consumedChannels(mod, elem) {
    const owns = moduleOwns[mod.type] ?? [];
    const offered = offeredChannels(elem);
    return owns.filter(ch => offered.has(ch));
  }

  // ---------------------------------------------------------------------------
  // Per-module parameters (merged from the former standalone ParameterTable)
  // ---------------------------------------------------------------------------

  /** Group assembly.parameters by module_id for inline display on cards. */
  $: paramsByModule = buildParamsByModule($assembly?.parameters ?? []);

  function buildParamsByModule(params) {
    const map = {};
    for (const p of params) {
      (map[p.module_id] ??= []).push(p);
    }
    return map;
  }

  // ---------------------------------------------------------------------------
  // Identifiability (per-parameter verdict; lazy-loaded on demand)
  // ---------------------------------------------------------------------------
  let identStatus = null;   // { param_status: { name: {status, reason, tau_h, correlation} } }
  let identLoading = false;
  let identError   = '';

  async function loadIdentifiability() {
    identLoading = true;
    identError   = '';
    try {
      identStatus = await fetchIdentifiability();
    } catch (err) {
      identError = err.message ?? String(err);
    } finally {
      identLoading = false;
    }
  }

  const STATUS_BADGE = {
    resolvable:      'badge-success',
    borderline:      'badge-warning',
    prior_dominated: 'badge-error',
  };
  const statusBadge = (s) => STATUS_BADGE[s] ?? 'badge-ghost';

  // Per-parameter "show contributions" toggle (keyed by param name).
  let expandedParam = {};
  const toggleParam = (name) =>
    (expandedParam = { ...expandedParam, [name]: !expandedParam[name] });

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
      await addModule(addModuleType, fields);
      // Stores are guaranteed fresh after the await (applyMutation invariant).
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
      await removeModule(mid);
      // Stores are guaranteed fresh after the await (applyMutation invariant).
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
      await routeModule(mod.id, [...current]);
      // Stores are guaranteed fresh after the await (applyMutation invariant).
    } catch (err) {
      alert(`Routing update failed: ${err.message}`);
    }
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

  // ---------------------------------------------------------------------------
  // Ownership-check collapse: auto-open when problems exist
  // ---------------------------------------------------------------------------
  $: hasProblems = ($assembly?.problems?.length ?? 0) > 0;
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
         Star topology — server-rendered RC schematic (schemdraw busbar)
    ===================================================================== -->
    <section>
      <h2 class="text-xl font-semibold mb-3">Topology</h2>
      {#if !schematicUrl || svgError}
        <div class="border border-base-300 rounded-lg p-6 text-center text-base-content/50 text-sm">
          No schematic yet — add a RoomMass and at least one module to render the
          RC star (T_room rail + module branches).
        </div>
      {:else}
        <div class="overflow-x-auto rounded-lg border border-base-300 bg-base-100 p-2">
          <img
            src={schematicUrl}
            alt="RC star schematic: T_room rail with each module as a branch to its boundary"
            class="mx-auto max-w-full"
            onerror={() => (svgError = true)}
          />
        </div>
      {/if}
    </section>

    <!-- ====================================================================
         Module list + routing controls
    ===================================================================== -->
    <section>
      <div class="flex items-center justify-between mb-3 gap-2 flex-wrap">
        <h2 class="text-xl font-semibold">Modules</h2>
        <button
          class="btn btn-outline btn-xs"
          onclick={loadIdentifiability}
          disabled={identLoading || !$assembly?.parameters?.length}
          title="Pre-fit verdict: which parameters the signals can resolve"
        >
          {#if identLoading}
            <span class="loading loading-spinner loading-xs"></span>
          {/if}
          Check identifiability
        </button>
      </div>
      {#if identError}
        <div role="alert" class="alert alert-error mb-3 text-sm">
          <span>{identError}</span>
        </div>
      {/if}

      {#if mods.length === 0}
        <p class="text-base-content/60 mb-3">No modules yet.</p>
      {:else}
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          {#each mods as mod}
            {@const owns = moduleOwns[mod.type] ?? []}
            {@const isRoomMass = owns.length === 0}
            {@const routableElements = elements.filter(e => moduleCanRouteElement(mod, e))}
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

                {#if isRoomMass}
                  <!-- RoomMass owns nothing — show its fields, no element checkboxes.
                       Its C_room prior is auto-derived from the IndoorMass STORAGE
                       budget by the assembler, so no routing is exposed here. -->
                  <div class="mt-2 text-xs text-base-content/60">
                    Owns no channels — C_room is auto-derived from IndoorMass.
                  </div>
                {:else if routableElements.length > 0}
                  <!-- Element routing checkboxes. One checkbox per element whose
                       offered channels overlap this module's owns set; the caption
                       under each names the channel(s) this module actually consumes
                       (the owns ∩ offered intersection), which may be a subset. -->
                  <div class="mt-3">
                    <div class="text-xs font-medium mb-1">
                      Routed elements
                      <span class="font-normal text-base-content/40">— owns {owns.join(', ')}</span>
                    </div>
                    <div class="flex flex-col gap-1.5">
                      {#each routableElements as elem}
                        {@const consumed = consumedChannels(mod, elem)}
                        <label class="flex items-start gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            class="checkbox checkbox-sm mt-0.5"
                            checked={mod.element_ids?.includes(elem.id)}
                            onchange={(e) => handleRoutingChange(mod, elem.id, e.target.checked)}
                          />
                          <span class="text-sm leading-tight">
                            {elem.label}
                            <span class="block text-xs text-base-content/40 font-mono">
                              → {consumed.join(', ')}
                            </span>
                          </span>
                        </label>
                      {/each}
                    </div>
                  </div>
                {:else}
                  <div class="mt-2 text-xs text-base-content/40">
                    No compatible elements (needs channels: {owns.join(', ')}).
                  </div>
                {/if}

                <!-- Parameters owned by this module: prior + identifiability +
                     collapsible budget contributions. Merged here from the former
                     standalone Thermal-parameters table. -->
                {#if paramsByModule[mod.id]?.length}
                  <div class="mt-3 pt-3 border-t border-base-200">
                    <div class="text-xs font-medium mb-1">Parameters</div>
                    <div class="flex flex-col gap-1">
                      {#each (paramsByModule[mod.id] ?? []) as param}
                        {@const ident = identStatus?.param_status?.[param.name]}
                        <div class="text-xs">
                          <div class="flex items-center gap-2 flex-wrap">
                            <span class="font-mono font-medium">{param.name}</span>
                            <span class="text-base-content/50 font-mono">
                              μ<sub>log</sub>={param.prior.mu_log.toFixed(2)}
                              σ<sub>log</sub>={param.prior.sigma_log.toFixed(2)}
                            </span>
                            {#if ident}
                              <span class="badge {statusBadge(ident.status)} badge-xs">
                                {ident.status.replace('_', ' ')}
                              </span>
                            {/if}
                            {#if param.contributions?.length}
                              <button
                                class="btn btn-ghost btn-xs h-auto min-h-0 py-0 px-1 text-base-content/50"
                                onclick={() => toggleParam(param.name)}
                                aria-expanded={!!expandedParam[param.name]}
                              >
                                {expandedParam[param.name] ? 'hide' : 'budgets'}
                              </button>
                            {/if}
                          </div>
                          {#if expandedParam[param.name] && param.contributions?.length}
                            <table class="table table-xs mt-1 mb-1">
                              <thead>
                                <tr class="text-base-content/50">
                                  <th>Element</th><th>Channel</th><th>Field</th>
                                  <th class="text-right">Value</th>
                                </tr>
                              </thead>
                              <tbody>
                                {#each param.contributions as c}
                                  <tr>
                                    <td>{c.element_label}</td>
                                    <td class="font-mono">{c.channel}</td>
                                    <td class="font-mono">{c.budget_field}</td>
                                    <td class="text-right font-mono">{c.value.toFixed(3)}</td>
                                  </tr>
                                {/each}
                              </tbody>
                            </table>
                          {/if}
                        </div>
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

            <!-- Module-type-specific fields (all current module types have fields: []) -->
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

    <!-- ====================================================================
         Ownership check — collapsible diagnostic matrix
         Collapsed by default; auto-expands when assembly problems exist.
    ===================================================================== -->
    <section>
      <!-- DaisyUI collapse with checkbox trick for programmatic open/close.
           When hasProblems is true we force the checkbox checked to expand it. -->
      <div class="collapse collapse-arrow border border-base-300 rounded-lg bg-base-100">
        <input
          type="checkbox"
          class="peer"
          id="ownership-check-toggle"
          checked={hasProblems}
          aria-label="Toggle ownership check panel"
        />
        <label
          for="ownership-check-toggle"
          class="collapse-title font-semibold text-sm cursor-pointer select-none peer-checked:text-base-content"
        >
          Ownership check
          {#if hasProblems}
            <span class="badge badge-error badge-xs ml-2 align-middle">{$assembly.problems.length}</span>
          {/if}
        </label>

        <div class="collapse-content">
          <p class="text-xs text-base-content/60 mb-3 mt-1">
            Each cell shows which module owns that (element, channel) combination.
            Red cells indicate a problem (double-count or unclaimed channel).
          </p>

          {#if elements.length === 0}
            <p class="text-base-content/60 text-sm">No elements — add elements first.</p>
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
        </div>
      </div>
    </section>

  {/if}
</div>
