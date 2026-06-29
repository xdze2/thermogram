<script>
  import ElementList    from './lib/ElementList.svelte';
  import ModuleGraph    from './lib/ModuleGraph.svelte';
  import ParameterTable from './lib/ParameterTable.svelte';
  import { loading, error, refreshAll } from './stores/model.js';
</script>

<div class="min-h-screen bg-base-100">

  <!-- App header -->
  <header class="navbar bg-base-200 border-b border-base-300 px-4 sticky top-0 z-10">
    <div class="navbar-start">
      <span class="text-xl font-bold tracking-tight">thnodes</span>
      <span class="ml-2 badge badge-ghost badge-sm hidden sm:inline-flex">single-room thermal sim</span>
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

    <!-- RIGHT COLUMN: how the room BEHAVES (results) -->
    <div class="flex flex-col divide-y divide-base-300">

      <!-- Right (unified): simulation controls + graphs + parameters -->
      <!-- ParameterTable already contains the scenario sliders (time range &
           signals) at the top and the graphs/parameter table below — both are
           shown in the right column as specified. -->
      <section aria-label="Simulation and results" class="flex-1">
        <ParameterTable />
      </section>

    </div>

  </main>

</div>
