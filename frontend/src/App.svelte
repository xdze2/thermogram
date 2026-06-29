<script>
  import ElementList    from './lib/ElementList.svelte';
  import ModuleGraph    from './lib/ModuleGraph.svelte';
  import ParameterTable from './lib/ParameterTable.svelte';
  import { loading, error, loadFixtures, refreshAll } from './stores/model.js';

  let activeTab = $state('elements');  // 'elements' | 'topology' | 'parameters'

  function setTab(tab) {
    activeTab = tab;
  }
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
      {#if import.meta.env.DEV}
        <button
          class="btn btn-ghost btn-xs"
          onclick={loadFixtures}
          title="Reload fixture data (dev only)"
        >
          Reload fixtures
        </button>
      {:else}
        <button
          class="btn btn-ghost btn-xs"
          onclick={refreshAll}
        >
          Refresh
        </button>
      {/if}
    </div>
  </header>

  <!-- Global error (outside tabs, so always visible) -->
  {#if $error}
    <div role="alert" class="alert alert-error rounded-none text-sm px-4 py-2">
      <span class="font-medium">Error:</span> {$error}
    </div>
  {/if}

  <!-- Tab navigation -->
  <div class="border-b border-base-300 bg-base-100 px-4">
    <div role="tablist" class="tabs tabs-border">
      <button
        role="tab"
        class="tab {activeTab === 'elements' ? 'tab-active' : ''}"
        aria-selected={activeTab === 'elements'}
        onclick={() => setTab('elements')}
      >
        Elements
      </button>
      <button
        role="tab"
        class="tab {activeTab === 'topology' ? 'tab-active' : ''}"
        aria-selected={activeTab === 'topology'}
        onclick={() => setTab('topology')}
      >
        Topology &amp; Routing
      </button>
      <button
        role="tab"
        class="tab {activeTab === 'parameters' ? 'tab-active' : ''}"
        aria-selected={activeTab === 'parameters'}
        onclick={() => setTab('parameters')}
      >
        Parameters &amp; Simulation
      </button>
    </div>
  </div>

  <!-- Tab panels -->
  <main class="max-w-5xl mx-auto">
    {#if activeTab === 'elements'}
      <ElementList />
    {:else if activeTab === 'topology'}
      <ModuleGraph />
    {:else if activeTab === 'parameters'}
      <ParameterTable />
    {/if}
  </main>

</div>
