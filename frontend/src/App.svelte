<script>
  import ElementList    from './lib/ElementList.svelte';
  import ModuleGraph    from './lib/ModuleGraph.svelte';
  import SimulationPanel from './lib/SimulationPanel.svelte';
  import StudiesPanel   from './lib/StudiesPanel.svelte';
  import ModelHome      from './lib/ModelHome.svelte';
  import { loading, error, refreshAll } from './stores/model.js';
  import { route, navigate } from './stores/route.js';
  import { setModelId } from './lib/api.js';

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

  /** Active right-column tab: 'simulate' | 'studies' */
  let rightTab = $state('simulate');
</script>

{#if $route.view === 'home'}

  <!-- -------------------------------------------------------------------- -->
  <!-- HOME VIEW — model list; rendered by ModelHome which manages its own  -->
  <!-- loading/error state. No model stores are active here.               -->
  <!-- -------------------------------------------------------------------- -->
  <ModelHome />

{:else}

  <!-- -------------------------------------------------------------------- -->
  <!-- EDITOR VIEW — 2-column split for the currently-open model.          -->
  <!-- The $effect above sets the active uid + reloads when the route resolves -->
  <!-- to this view (initial load or navigation from home).                     -->
  <!-- -------------------------------------------------------------------- -->
  <div class="min-h-screen bg-base-100">

    <!-- App header -->
    <header class="navbar bg-base-200 border-b border-base-300 px-4 sticky top-0 z-10">
      <div class="navbar-start gap-2">
        <button
          class="btn btn-ghost btn-sm"
          onclick={() => navigate('#/')}
          title="Back to model list"
          aria-label="Back to home"
        >
          &#8592; Models
        </button>
        <span class="text-xl font-bold tracking-tight">thnodes</span>
        <span class="ml-1 badge badge-ghost badge-sm hidden sm:inline-flex">single-room thermal sim</span>
      </div>
      <div class="navbar-end gap-2">
        {#if $loading}
          <span class="loading loading-spinner loading-sm text-primary"></span>
        {/if}
        <button
          class="btn btn-ghost btn-xs"
          onclick={refreshAll}
          title="Re-pull document, assembly, and registry from the server"
        >
          Refresh
        </button>
      </div>
    </header>

    <!-- Global error (always visible) -->
    {#if $error}
      <div role="alert" class="alert alert-error rounded-none text-sm px-4 py-2">
        <span class="font-medium">Error:</span> {$error}
      </div>
    {/if}

    <!-- 2-column split: left = authoring/structure, right = behavior/results -->
    <!-- On lg+ screens: side-by-side. Below lg: stack vertically (left first). -->
    <main class="grid grid-cols-1 lg:grid-cols-2 lg:divide-x lg:divide-base-300 min-h-[calc(100vh-4rem)]">

      <!-- LEFT COLUMN: what the room IS (authoring / structure) -->
      <div class="flex flex-col divide-y divide-base-300">

        <!-- Left-top: Elements -->
        <section aria-label="Building elements">
          <ElementList />
        </section>

        <!-- Left-bottom: Topology + modules + routing + ownership check -->
        <section aria-label="Topology and routing">
          <ModuleGraph />
        </section>

      </div>

      <!-- RIGHT COLUMN: how the room BEHAVES (results + studies) -->
      <div class="flex flex-col">

        <!-- Tab bar for the right column -->
        <div class="tabs tabs-border px-4 pt-3 border-b border-base-300" role="tablist" aria-label="Right panel view">
          <button
            class="tab {rightTab === 'simulate' ? 'tab-active' : ''}"
            role="tab"
            aria-selected={rightTab === 'simulate'}
            aria-controls="panel-simulate"
            onclick={() => { rightTab = 'simulate'; }}
          >
            Simulation
          </button>
          <button
            class="tab {rightTab === 'studies' ? 'tab-active' : ''}"
            role="tab"
            aria-selected={rightTab === 'studies'}
            aria-controls="panel-studies"
            onclick={() => { rightTab = 'studies'; }}
          >
            Studies
          </button>
        </div>

        <!-- Simulation panel -->
        <section
          id="panel-simulate"
          role="tabpanel"
          aria-label="Simulation and results"
          class="flex-1 {rightTab !== 'simulate' ? 'hidden' : ''}"
        >
          <SimulationPanel />
        </section>

        <!-- Studies panel -->
        <section
          id="panel-studies"
          role="tabpanel"
          aria-label="Studies"
          class="flex-1 {rightTab !== 'studies' ? 'hidden' : ''}"
        >
          <StudiesPanel modelId={$route.uid} />
        </section>

      </div>

    </main>

  </div>

{/if}
