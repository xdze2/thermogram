<script>
  /**
   * ModelHome.svelte — model-management home page.
   *
   * Shown at route #/ (empty hash). Lists all models, lets the user open,
   * rename, or delete them, create a blank new model, or clone an example.
   *
   * State is local to this component (model-list ops are NOT document/assembly
   * mutations — they do not go through applyMutation). Model-management calls
   * the api.js model functions directly and re-fetches the list after each change.
   */
  import { navigate } from '../stores/route.js';
  import {
    listModels,
    createModel,
    listExamples,
    createFromExample,
    renameModel,
    deleteModel,
  } from '../lib/api.js';

  // ---------------------------------------------------------------------------
  // Local state
  // ---------------------------------------------------------------------------

  /** @type {{ uid: string, name: string }[]} */
  let models = [];
  /** @type {{ key: string, name: string }[]} */
  let examples = [];
  let listLoading = false;
  let listError = '';

  // Create-new form
  let newModelName = '';
  let creating = false;

  // From-example form
  let selectedExampleKey = '';
  let exampleName = '';
  let creatingFromExample = false;

  // Rename inline edit: uid being renamed
  let renamingUid = '';
  let renameValue = '';
  let renaming = false;

  // Delete confirmation: uid to delete
  let deletingUid = '';
  let deleting = false;

  // ---------------------------------------------------------------------------
  // Load list + examples on mount
  // ---------------------------------------------------------------------------

  async function loadAll() {
    listLoading = true;
    listError = '';
    try {
      [models, examples] = await Promise.all([listModels(), listExamples()]);
      if (examples.length > 0 && !selectedExampleKey) {
        selectedExampleKey = examples[0].key;
      }
    } catch (err) {
      listError = err.message ?? String(err);
    } finally {
      listLoading = false;
    }
  }

  // Run on component mount (Svelte 4: use onMount or a reactive initialiser)
  import { onMount } from 'svelte';
  onMount(loadAll);

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  async function handleCreateModel() {
    creating = true;
    listError = '';
    try {
      const model = await createModel(newModelName.trim() || undefined);
      newModelName = '';
      await loadAll();
      // Navigate directly into the new model
      navigate(`#/models/${model.uid}`);
    } catch (err) {
      listError = err.message ?? String(err);
    } finally {
      creating = false;
    }
  }

  async function handleCreateFromExample() {
    if (!selectedExampleKey) return;
    creatingFromExample = true;
    listError = '';
    try {
      const model = await createFromExample(
        selectedExampleKey,
        exampleName.trim() || undefined,
      );
      exampleName = '';
      await loadAll();
      navigate(`#/models/${model.uid}`);
    } catch (err) {
      listError = err.message ?? String(err);
    } finally {
      creatingFromExample = false;
    }
  }

  function startRename(uid, currentName) {
    renamingUid = uid;
    renameValue = currentName;
  }

  function cancelRename() {
    renamingUid = '';
    renameValue = '';
  }

  async function commitRename(uid) {
    if (!renameValue.trim()) {
      cancelRename();
      return;
    }
    renaming = true;
    listError = '';
    try {
      await renameModel(uid, renameValue.trim());
      cancelRename();
      await loadAll();
    } catch (err) {
      listError = err.message ?? String(err);
    } finally {
      renaming = false;
    }
  }

  function requestDelete(uid) {
    deletingUid = uid;
  }

  function cancelDelete() {
    deletingUid = '';
  }

  async function confirmDelete(uid) {
    deleting = true;
    listError = '';
    try {
      await deleteModel(uid);
      deletingUid = '';
      await loadAll();
    } catch (err) {
      listError = err.message ?? String(err);
    } finally {
      deleting = false;
    }
  }

  function openModel(uid) {
    navigate(`#/models/${uid}`);
  }

  function handleRenameKeydown(e, uid) {
    if (e.key === 'Enter') commitRename(uid);
    if (e.key === 'Escape') cancelRename();
  }
</script>

<div class="flex-1 overflow-auto bg-base-100">

  <main class="max-w-2xl mx-auto px-4 py-8 flex flex-col gap-8">

    <!-- Page title — sidebar carries the app mark; this identifies the view -->
    <div class="flex items-center gap-3">
      <h1 class="text-xl font-bold tracking-tight">Models</h1>
      {#if listLoading}
        <span class="loading loading-spinner loading-sm text-primary"></span>
      {/if}
    </div>

    <!-- Global error -->
    {#if listError}
      <div role="alert" class="alert alert-error text-sm">
        <span>{listError}</span>
        <button class="btn btn-xs btn-ghost" onclick={() => { listError = ''; }}>Dismiss</button>
      </div>
    {/if}

    <!-- ------------------------------------------------------------------ -->
    <!-- Model list                                                          -->
    <!-- ------------------------------------------------------------------ -->
    <section aria-label="Your models">
      <h2 class="text-lg font-semibold mb-3">Your models</h2>

      {#if listLoading && models.length === 0}
        <div class="flex justify-center py-8">
          <span class="loading loading-spinner loading-md text-primary"></span>
        </div>
      {:else if models.length === 0}
        <p class="text-base-content/60 text-sm">No models yet. Create one below.</p>
      {:else}
        <ul class="flex flex-col gap-2">
          {#each models as model (model.uid)}
            <li class="card bg-base-200 shadow-sm">
              <div class="card-body p-4 flex flex-row items-center gap-3">

                {#if renamingUid === model.uid}
                  <!-- Inline rename -->
                  <input
                    class="input input-bordered input-sm flex-1"
                    type="text"
                    aria-label="New name for {model.name}"
                    bind:value={renameValue}
                    onkeydown={(e) => handleRenameKeydown(e, model.uid)}
                    disabled={renaming}
                  />
                  <button
                    class="btn btn-primary btn-sm"
                    onclick={() => commitRename(model.uid)}
                    disabled={renaming}
                  >
                    {#if renaming}
                      <span class="loading loading-spinner loading-xs"></span>
                    {:else}
                      Save
                    {/if}
                  </button>
                  <button
                    class="btn btn-ghost btn-sm"
                    onclick={cancelRename}
                    disabled={renaming}
                  >
                    Cancel
                  </button>

                {:else if deletingUid === model.uid}
                  <!-- Delete confirmation -->
                  <span class="flex-1 text-sm">
                    Delete <strong>{model.name}</strong>? This cannot be undone.
                  </span>
                  <button
                    class="btn btn-error btn-sm"
                    onclick={() => confirmDelete(model.uid)}
                    disabled={deleting}
                  >
                    {#if deleting}
                      <span class="loading loading-spinner loading-xs"></span>
                    {:else}
                      Delete
                    {/if}
                  </button>
                  <button
                    class="btn btn-ghost btn-sm"
                    onclick={cancelDelete}
                    disabled={deleting}
                  >
                    Cancel
                  </button>

                {:else}
                  <!-- Normal row -->
                  <span class="flex-1 font-medium truncate" title={model.uid}>
                    {model.name}
                  </span>
                  <button
                    class="btn btn-primary btn-sm"
                    onclick={() => openModel(model.uid)}
                  >
                    Open
                  </button>
                  <button
                    class="btn btn-ghost btn-sm"
                    onclick={() => startRename(model.uid, model.name)}
                    aria-label="Rename {model.name}"
                  >
                    Rename
                  </button>
                  <button
                    class="btn btn-ghost btn-sm text-error hover:bg-error hover:text-error-content"
                    onclick={() => requestDelete(model.uid)}
                    aria-label="Delete {model.name}"
                  >
                    Remove
                  </button>
                {/if}

              </div>
            </li>
          {/each}
        </ul>
      {/if}
    </section>

    <!-- ------------------------------------------------------------------ -->
    <!-- Create a blank new model                                           -->
    <!-- ------------------------------------------------------------------ -->
    <section aria-label="Create new model">
      <h2 class="text-lg font-semibold mb-3">New model</h2>
      <form
        class="flex gap-2 items-end flex-wrap"
        onsubmit={(e) => { e.preventDefault(); handleCreateModel(); }}
      >
        <div class="form-control flex-1 min-w-48">
          <label class="label pb-1" for="new-model-name">
            <span class="label-text">Name (optional)</span>
          </label>
          <input
            id="new-model-name"
            class="input input-bordered input-sm"
            type="text"
            placeholder="My room"
            bind:value={newModelName}
            disabled={creating}
          />
        </div>
        <button
          type="submit"
          class="btn btn-primary btn-sm"
          disabled={creating}
        >
          {#if creating}
            <span class="loading loading-spinner loading-xs"></span>
          {/if}
          Create
        </button>
      </form>
    </section>

    <!-- ------------------------------------------------------------------ -->
    <!-- Create from example                                                -->
    <!-- ------------------------------------------------------------------ -->
    {#if examples.length > 0}
      <section aria-label="Create model from example">
        <h2 class="text-lg font-semibold mb-3">New from example</h2>
        <form
          class="flex gap-2 items-end flex-wrap"
          onsubmit={(e) => { e.preventDefault(); handleCreateFromExample(); }}
        >
          <div class="form-control flex-1 min-w-48">
            <label class="label pb-1" for="example-select">
              <span class="label-text">Example</span>
            </label>
            <select
              id="example-select"
              class="select select-bordered select-sm"
              bind:value={selectedExampleKey}
              disabled={creatingFromExample}
            >
              {#each examples as ex (ex.key)}
                <option value={ex.key}>{ex.name}</option>
              {/each}
            </select>
          </div>
          <div class="form-control flex-1 min-w-48">
            <label class="label pb-1" for="example-name">
              <span class="label-text">Name (optional)</span>
            </label>
            <input
              id="example-name"
              class="input input-bordered input-sm"
              type="text"
              placeholder="My copy"
              bind:value={exampleName}
              disabled={creatingFromExample}
            />
          </div>
          <button
            type="submit"
            class="btn btn-secondary btn-sm"
            disabled={creatingFromExample || !selectedExampleKey}
          >
            {#if creatingFromExample}
              <span class="loading loading-spinner loading-xs"></span>
            {/if}
            Create from example
          </button>
        </form>
      </section>
    {/if}

  </main>
</div>
