<script>
  import { onMount } from 'svelte';
  import { navigate } from './store.js';
  import { fetchJson } from './api.js';

  let studies = [];
  let loading = true;
  let error = '';
  let renamingId = null;
  let renamingValue = '';

  onMount(() => refresh());

  async function refresh() {
    loading = true;
    error = '';
    try {
      studies = await fetchJson('/api/studies');
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function createStudy() {
    const r = await fetch('/api/studies', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'New study' }),
    });
    if (!r.ok) { error = `Create failed: ${r.status}`; return; }
    const s = await r.json();
    navigate(`study/${s.id}`);
  }

  async function deleteStudy(id) {
    if (!confirm('Delete this study?')) return;
    const r = await fetch(`/api/studies/${id}`, { method: 'DELETE' });
    if (!r.ok) { error = `Delete failed: ${r.status}`; return; }
    await refresh();
  }

  async function duplicateStudy(id) {
    const r = await fetch(`/api/studies/${id}/duplicate`, { method: 'POST' });
    if (!r.ok) { error = `Duplicate failed: ${r.status}`; return; }
    await refresh();
  }

  function startRename(s) {
    renamingId = s.id;
    renamingValue = s.name;
  }

  async function commitRename(id) {
    const r = await fetch(`/api/studies/${id}/name`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: renamingValue }),
    });
    renamingId = null;
    if (!r.ok) { error = `Rename failed: ${r.status}`; return; }
    await refresh();
  }

  function fmtDate(iso) {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  }
</script>

<div class="max-w-2xl mx-auto p-8">
  <!-- Header -->
  <div class="flex items-center justify-between mb-6">
    <h1 class="text-sm uppercase tracking-widest text-base-content/50">thermal nodes · studies</h1>
    <button class="btn btn-sm btn-primary" on:click={createStudy}>+ new study</button>
  </div>

  {#if error}
    <div class="alert alert-error text-xs mb-4">{error}</div>
  {/if}

  {#if loading}
    <div class="text-xs text-base-content/40">loading…</div>
  {:else if studies.length === 0}
    <div class="text-xs text-base-content/30 py-12 text-center">
      No studies yet.<br />
      <button class="link link-primary mt-2" on:click={createStudy}>Create your first study</button>
    </div>
  {:else}
    <div class="flex flex-col gap-1">
      {#each studies as s (s.id)}
        <div class="flex items-center gap-2 px-3 py-2 rounded hover:bg-base-200 group">
          <!-- Name (clickable / inline rename) -->
          {#if renamingId === s.id}
            <input
              class="input input-xs flex-1 font-mono"
              bind:value={renamingValue}
              on:blur={() => commitRename(s.id)}
              on:keydown={(e) => { if (e.key === 'Enter') commitRename(s.id); if (e.key === 'Escape') renamingId = null; }}
              autofocus
            />
          {:else}
            <button
              class="flex-1 text-left text-sm hover:text-primary truncate"
              on:click={() => navigate(`study/${s.id}`)}
            >{s.name}</button>
          {/if}

          <!-- Updated at -->
          <span class="text-xs text-base-content/30 shrink-0 hidden group-hover:inline">{fmtDate(s.updated_at)}</span>

          <!-- Actions (visible on hover) -->
          <div class="flex gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
            <button
              class="btn btn-xs btn-ghost"
              title="Rename"
              on:click={() => startRename(s)}
            >✎</button>
            <button
              class="btn btn-xs btn-ghost"
              title="Duplicate"
              on:click={() => duplicateStudy(s.id)}
            >⧉</button>
            <button
              class="btn btn-xs btn-ghost text-error"
              title="Delete"
              on:click={() => deleteStudy(s.id)}
            >✕</button>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
