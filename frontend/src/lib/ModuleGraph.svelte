<script>
  import { assembly, roomDoc, registry, loading, error } from '../stores/model.js';
  import { topologySvgUrl, fetchIdentifiability } from '../lib/api.js';

  // ---------------------------------------------------------------------------
  // Channels (fixed set per contract — used in the ownership diagnostic matrix)
  // ---------------------------------------------------------------------------
  const CHANNELS = ['CONDUCTION', 'SOLAR_TRANSMISSION', 'SOLAR_OPAQUE', 'STORAGE'];

  // ---------------------------------------------------------------------------
  // Server-rendered schematic (schemdraw from /topology.svg).
  // Cache-bust on every assembly change so the browser reloads the image.
  // svgError toggles a fallback message when the room is incomplete (400).
  // ---------------------------------------------------------------------------
  let svgError = false;
  $: schematicUrl = $assembly
    ? `${topologySvgUrl()}?v=${assemblyVersion($assembly)}`
    : '';
  $: if (schematicUrl) svgError = false;

  function assemblyVersion(asm) {
    const own = (asm.ownership ?? [])
      .map(o => `${o.element_id}:${o.channel}:${o.module_id}`)
      .join(',');
    const prob = (asm.problems ?? []).length;
    return encodeURIComponent(`${own}|${prob}`);
  }

  // ---------------------------------------------------------------------------
  // Derived: elements, modules (derived read-only), ownership map, problems
  // ---------------------------------------------------------------------------
  $: elements = $roomDoc?.elements ?? [];
  $: mods     = $roomDoc?.modules ?? [];

  $: ownershipMap = buildOwnershipMap($assembly?.ownership ?? []);
  $: problemSet   = buildProblemSet($assembly?.problems ?? []);

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
  // Per-module parameters (from assembly.parameters)
  // ---------------------------------------------------------------------------
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
  let identStatus  = null;
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
  // Ownership-check collapse: auto-open when problems exist
  // ---------------------------------------------------------------------------
  $: hasProblems = ($assembly?.problems?.length ?? 0) > 0;

  // ---------------------------------------------------------------------------
  // Ownership matrix cell helpers
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
    // Truncate long derived-module IDs for the compact matrix display
    return mid.length > 20 ? mid.slice(0, 18) + '…' : mid;
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

    <!-- ======================================================================
         Star topology — server-rendered RC schematic (schemdraw via /topology.svg)
    ====================================================================== -->
    <section aria-label="Topology schematic">
      <h2 class="text-xl font-semibold mb-3">Topology</h2>
      {#if !schematicUrl || svgError}
        <div class="border border-base-300 rounded-lg p-6 text-center text-base-content/50 text-sm">
          No schematic yet — add an IndoorMass and at least one more element to
          render the RC star (T_room rail + module branches).
        </div>
      {:else}
        <div class="overflow-x-auto rounded-lg border border-base-300 bg-base-100 p-2">
          <img
            src={schematicUrl}
            alt="RC star schematic: T_room rail with each derived module as a branch to its boundary signal"
            class="mx-auto max-w-full"
            onerror={() => (svgError = true)}
          />
        </div>
      {/if}
    </section>

    <!-- ======================================================================
         Derived module list — read-only.
         Modules are computed by the server's grouping rule from element
         boundaries; the user does not add, remove, or route them.
    ====================================================================== -->
    <section aria-label="Derived modules">
      <div class="flex items-center justify-between mb-3 gap-2 flex-wrap">
        <h2 class="text-xl font-semibold">Derived modules</h2>
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
        <p class="text-base-content/60 mb-3 text-sm">
          No derived modules yet — add elements with boundary fields set.
        </p>
      {:else}
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-2">
          {#each mods as mod (mod.id)}
            <div class="card card-border bg-base-100 shadow-sm">
              <div class="card-body p-4">
                <!-- Module header: stable ID in ModuleType[Signal] notation -->
                <div>
                  <span class="badge badge-outline badge-sm font-mono">{mod.id}</span>
                  {#if mod.signal}
                    <div class="text-xs text-base-content/50 mt-0.5">
                      boundary: <span class="font-mono">{mod.signal}</span>
                    </div>
                  {:else}
                    <div class="text-xs text-base-content/50 mt-0.5">interior (no boundary signal)</div>
                  {/if}
                </div>

                <!-- Element membership (computed by grouping rule — read-only) -->
                {#if mod.element_ids?.length}
                  <div class="mt-2 text-xs text-base-content/60">
                    <span class="font-medium">Elements:</span>
                    {mod.element_ids.join(', ')}
                  </div>
                {/if}

                <!-- Parameters owned by this module -->
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
    </section>

    <!-- ======================================================================
         Assembly diagnostic — collapsed by default; auto-expands on problems.
         "problems" now means an engine bug in the grouping rule, not user error.
         The matrix stays quiet for well-formed rooms.
    ====================================================================== -->
    <section aria-label="Assembly diagnostic">
      <div class="collapse collapse-arrow border border-base-300 rounded-lg bg-base-100">
        <input
          type="checkbox"
          class="peer"
          id="ownership-check-toggle"
          checked={hasProblems}
          aria-label="Toggle assembly diagnostic"
        />
        <label
          for="ownership-check-toggle"
          class="collapse-title font-semibold text-sm cursor-pointer select-none peer-checked:text-base-content"
        >
          Assembly diagnostic
          <span class="font-normal text-base-content/40 ml-1">— should be empty</span>
          {#if hasProblems}
            <span class="badge badge-error badge-xs ml-2 align-middle">
              {$assembly.problems.length}
            </span>
          {/if}
        </label>

        <div class="collapse-content">
          <p class="text-xs text-base-content/60 mb-3 mt-1">
            Each cell shows which derived module owns that (element, channel)
            combination. A non-empty problems list indicates a bug in the grouping
            rule, not a user error — please report it. Red cells flag the
            problematic (element, channel) pairs.
          </p>

          {#if elements.length === 0}
            <p class="text-base-content/60 text-sm">No elements — nothing to show.</p>
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
                        {@const hasBudget = elem.budgets?.[ch] &&
                          Object.values(elem.budgets[ch]).some(v => v !== null)}
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
