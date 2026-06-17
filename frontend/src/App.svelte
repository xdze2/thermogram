<script>
  import { route, theme, navigate } from './lib/store.js';
  import StudiesList from './lib/StudiesList.svelte';
  import StudyEditor from './lib/StudyEditor.svelte';

  let themeMenuOpen = false;

  $: {
    document.documentElement.setAttribute('data-theme', $theme);
    localStorage.setItem('theme', $theme);
  }

  function setTheme(t) {
    theme.set(t);
    themeMenuOpen = false;
  }

  function onDocClick(e) {
    if (!e.target.closest('#theme-btn-area')) themeMenuOpen = false;
  }
</script>

<svelte:document on:click={onDocClick} />

<!-- Topbar -->
<div class="bg-base-200 border-b border-base-300 py-2 px-4 flex items-center justify-between">
  <div class="flex items-center gap-3">
    <button
      class="text-xs tracking-widest uppercase text-base-content/50 hover:text-base-content/80 transition-colors"
      on:click={() => navigate('')}
    >thermal nodes</button>
    {#if $route.page === 'study'}
      <span class="text-base-content/20 text-xs">/</span>
      <span class="text-xs text-base-content/30">study</span>
    {/if}
  </div>
  <div class="flex items-center gap-3">
    <a href="/docs" target="_blank" class="text-xs text-base-content/40 hover:text-base-content/80 transition-colors">API docs</a>
    <div class="relative" id="theme-btn-area">
      <button
        class="text-xs text-base-content/40 hover:text-base-content/80 transition-colors"
        on:click|stopPropagation={() => themeMenuOpen = !themeMenuOpen}
      >theme</button>
      {#if themeMenuOpen}
        <div class="absolute right-0 top-6 z-50 bg-base-200 border border-base-300 rounded shadow-lg py-1 min-w-28">
          <button class="block w-full text-left px-3 py-1 text-xs hover:bg-base-300" on:click={() => setTheme('dark')}>dark</button>
          <button class="block w-full text-left px-3 py-1 text-xs hover:bg-base-300" on:click={() => setTheme('light')}>light</button>
        </div>
      {/if}
    </div>
  </div>
</div>

<!-- Page content -->
{#if $route.page === 'list'}
  <StudiesList />
{:else if $route.page === 'study'}
  <StudyEditor studyId={$route.id} />
{/if}
