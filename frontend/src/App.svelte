<script>
  import ElementList    from './lib/ElementList.svelte';
  import ModuleGraph    from './lib/ModuleGraph.svelte';
  import StudiesPanel   from './lib/StudiesPanel.svelte';
  import SignalBindingPanel from './lib/SignalBindingPanel.svelte';
  import ModelHome      from './lib/ModelHome.svelte';
  import { assembly, loading, error, refreshAll } from './stores/model.js';
  import { route, navigate } from './stores/route.js';
  import { setModelId, fetchIdentifiability } from './lib/api.js';

  // When the route changes to editor (navigation from home, or hash edited
  // manually), point the API client at the new uid and reload the model stores.
  // We track the last uid we loaded to avoid re-fetching on unrelated re-renders.
  let lastLoadedUid = '';

  $effect(() => {
    const r = $route;
    if (r.view === 'editor' && r.uid && r.uid !== lastLoadedUid) {
      lastLoadedUid = r.uid;
      setModelId(r.uid);
      refreshAll();
    }
  });

  // ---------------------------------------------------------------------------
  // Identifiability (left column, bottom section)
  // ---------------------------------------------------------------------------
  let identStatus  = $state(null);
  let identLoading = $state(false);
  let identError   = $state('');

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

  function statusBadge(s) {
    return STATUS_BADGE[s] ?? 'badge-ghost';
  }
</script>

<!-- ============================================================================ -->
<!-- GLOBAL SHELL — persistent left icon sidebar + content area for all views.   -->
<!-- The sidebar adapts its middle and bottom sections to the current route.      -->
<!-- ============================================================================ -->
<div class="flex h-screen overflow-hidden bg-base-100">

  <!-- -------------------------------------------------------------------------- -->
  <!-- LEFT ICON SIDEBAR (~48 px) — VSCode-style activity bar                    -->
  <!-- -------------------------------------------------------------------------- -->
  <nav
    class="flex flex-col items-center gap-1 w-12 shrink-0 bg-base-300 border-r border-base-300 py-2 z-10"
    aria-label="Activity bar"
  >

    <!-- App mark — always visible on every view -->
    <div
      class="flex items-center justify-center w-9 h-9 rounded font-black text-sm text-base-content select-none mb-1"
      title="thnodes — single-room thermal sim"
      aria-label="thnodes"
    >
      tn
    </div>

    <div class="divider my-0 px-2"></div>

    {#if $route.view === 'editor'}
      <!-- Back to model list (editor only) -->
      <button
        class="btn btn-ghost btn-sm w-9 h-9 p-0 text-base-content/70 hover:text-base-content"
        onclick={() => navigate('#/')}
        title="Back to model list"
        aria-label="Back to model list"
      >
        <!-- Home icon (Heroicons solid, 20 px) -->
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5" aria-hidden="true">
          <path fill-rule="evenodd" d="M9.293 2.293a1 1 0 0 1 1.414 0l7 7A1 1 0 0 1 17 11h-1v6a1 1 0 0 1-1 1h-3a1 1 0 0 1-1-1v-3H9v3a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-6H3a1 1 0 0 1-.707-1.707l7-7Z" clip-rule="evenodd" />
        </svg>
      </button>
    {/if}

    <!--
      Future top-level page icons land here, e.g.:
        Live view  — navigate('#/live')
        Materials DB — navigate('#/materials')
      Each gets the same btn btn-ghost btn-sm w-9 h-9 p-0 treatment with a title.
    -->

    <!-- Spacer pushes status indicators to the bottom of the bar -->
    <div class="flex-1"></div>

    {#if $route.view === 'editor'}
      <!-- Loading spinner (while in flight) or Refresh button (when idle) -->
      {#if $loading}
        <span
          class="loading loading-spinner loading-sm text-primary"
          aria-label="Loading…"
          title="Loading…"
        ></span>
      {:else}
        <button
          class="btn btn-ghost btn-sm w-9 h-9 p-0 text-base-content/70 hover:text-base-content"
          onclick={refreshAll}
          title="Re-pull document, assembly, and registry from the server"
          aria-label="Refresh model data"
        >
          <!-- Arrow-path / ↻ icon (Heroicons solid, 20 px) -->
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5" aria-hidden="true">
            <path fill-rule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.39Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0V5.36l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z" clip-rule="evenodd" />
          </svg>
        </button>
      {/if}

      <!-- Error indicator dot — signals the error banner visible in the content area -->
      {#if $error}
        <div
          class="w-3 h-3 rounded-full bg-error mb-1"
          title="Error — see banner above content"
          aria-label="Error indicator"
        ></div>
      {/if}
    {/if}

  </nav>

  <!-- -------------------------------------------------------------------------- -->
  <!-- CONTENT AREA — fills the viewport to the right of the sidebar             -->
  <!-- -------------------------------------------------------------------------- -->
  <div class="flex flex-col flex-1 min-w-0 overflow-hidden">

    {#if $route.view === 'home'}

      <!-- -------------------------------------------------------------------- -->
      <!-- HOME VIEW — model list. ModelHome manages its own loading/error.     -->
      <!-- -------------------------------------------------------------------- -->
      <ModelHome />

    {:else}

      <!-- -------------------------------------------------------------------- -->
      <!-- EDITOR VIEW — error banner + 2-column authoring/results split.       -->
      <!-- -------------------------------------------------------------------- -->

      <!-- Global error banner (always visible when set) -->
      {#if $error}
        <div role="alert" class="alert alert-error rounded-none text-sm px-4 py-2 shrink-0">
          <span class="font-medium">Error:</span> {$error}
        </div>
      {/if}

      <!-- 2-column split: left = authoring/structure, right = behavior/results -->
      <!-- On lg+ screens: side-by-side. Below lg: stack vertically (left first). -->
      <main class="grid grid-cols-1 lg:grid-cols-2 lg:divide-x lg:divide-base-300 flex-1 overflow-auto">

        <!-- LEFT COLUMN: what the room IS (authoring / structure) -->
        <div class="flex flex-col divide-y divide-base-300 overflow-y-auto">

          <!-- 1. Elements -->
          <section aria-label="Building elements">
            <ElementList />
          </section>

          <!-- 2. Required signals + sensor bindings -->
          <section aria-label="Required signals">
            <div class="p-4">
              <h2 class="text-sm font-medium text-base-content/70 uppercase tracking-wider mb-2">Required signals</h2>
              <SignalBindingPanel />
            </div>
          </section>

          <!-- 3. Topology + modules + routing + ownership check -->
          <section aria-label="Topology and routing">
            <ModuleGraph />
          </section>

          <!-- 4. Identifiability (pre-fit verdict) -->
          <section aria-label="Identifiability">
            <div class="p-4 space-y-3">
              <div class="flex items-center gap-2">
                <h2 class="text-sm font-medium text-base-content/70 uppercase tracking-wider">Identifiability</h2>
                <span class="badge badge-ghost badge-xs">pre-fit verdict</span>
              </div>
              <p class="text-xs text-base-content/50">
                Predicts which parameters the observed signals can resolve before running
                any Bayesian inference. Computed from the eigenstructure of the linearised
                system and broadband signal statistics.
              </p>

              {#if identLoading}
                <div class="flex justify-center py-4">
                  <span class="loading loading-spinner loading-md" aria-label="Checking identifiability…"></span>
                </div>
              {:else if identError}
                <div role="alert" class="alert alert-error text-sm py-2">
                  <span>{identError}</span>
                </div>
              {:else if identStatus}
                <div class="overflow-x-auto">
                  <table class="table table-xs w-full">
                    <thead>
                      <tr>
                        <th>Parameter</th>
                        <th>Status</th>
                        <th class="text-right">&tau; (h)</th>
                        <th class="text-right">Max corr.</th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each Object.entries(identStatus.param_status) as [name, info]}
                        <tr class="hover">
                          <td class="font-mono text-xs">{name}</td>
                          <td>
                            <span class="badge {statusBadge(info.status)} badge-xs">
                              {info.status.replace('_', ' ')}
                            </span>
                          </td>
                          <td class="text-right font-mono text-xs">
                            {info.tau_h != null ? info.tau_h.toFixed(1) : '—'}
                          </td>
                          <td class="text-right font-mono text-xs">
                            {info.correlation != null ? info.correlation.toFixed(2) : '—'}
                          </td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                </div>
              {:else}
                <p class="text-xs text-base-content/50">
                  Press the button below to compute verdicts.
                </p>
              {/if}

              <button
                class="btn btn-outline btn-sm"
                onclick={loadIdentifiability}
                disabled={identLoading || !$assembly?.parameters?.length}
              >
                {identLoading ? 'Checking…' : 'Run identifiability check'}
              </button>
            </div>
          </section>

        </div>

        <!-- RIGHT COLUMN: how the room BEHAVES (results + studies) -->
        <div class="flex flex-col overflow-hidden">
          <StudiesPanel modelId={$route.uid} />
        </div>

      </main>

    {/if}

  </div>

</div>
