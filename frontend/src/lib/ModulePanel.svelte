<script>
  // The assembled-module readout: what the room's elements + materials routed into.
  // Driven entirely by RCModelOut (modules / signals_required / n_states /
  // identifiability_warning) — read-only; the *choice* (heavy/light per element) is a
  // future per-element override. `availableSignals` lets us flag a required driving
  // signal the study hasn't wired up yet (a fit concern).

  export let rcResult = null;
  export let availableSignals = [];  // signal names the study has selected/fetched

  $: modules = rcResult?.modules ?? [];
  $: required = rcResult?.signals_required ?? [];
  $: nStates = rcResult?.n_states ?? 0;
  $: nParams = rcResult?.n_free_params ?? 0;
  $: warning = rcResult?.identifiability_warning ?? null;

  // A required signal is "missing" only if the study has *some* signals wired but not
  // this one. With nothing wired yet we don't nag (the user hasn't reached the fit step).
  $: have = new Set(availableSignals);
  $: missing = have.size > 0 ? required.filter(s => !have.has(s)) : [];

  const FORM_BADGE = {
    Conductance: 'resistor',
    DelayedConductance: 'R–C–R',
    SolarGain: 'flux',
    SourceFlux: 'flux',
    '—': 'node',
  };
</script>

<div>
  <div class="flex items-baseline gap-2 mb-2">
    <p class="text-xs uppercase tracking-widest text-base-content/30">Model</p>
    {#if rcResult}
      <span class="badge badge-xs badge-ghost tabular-nums">{nStates} state{nStates === 1 ? '' : 's'}</span>
      <span class="badge badge-xs badge-ghost tabular-nums">{nParams} param{nParams === 1 ? '' : 's'}</span>
    {/if}
  </div>

  {#if !rcResult}
    <p class="text-xs text-base-content/30">Describe the room to assemble its model.</p>
  {:else}
    <!-- Module rows -->
    <div class="flex flex-col gap-1">
      {#each modules as m}
        <div class="grid items-baseline gap-2 text-xs"
             style="grid-template-columns: 1fr auto">
          <div class="min-w-0">
            <span class="font-semibold text-base-content/70">{m.name}</span>
            {#if m.count > 1}<span class="text-base-content/40">×{m.count}</span>{/if}
            <span class="badge badge-xs badge-ghost ml-1 text-base-content/30">{FORM_BADGE[m.form] ?? m.form}</span>
            {#if m.element}<span class="text-base-content/30 ml-1 truncate" title={m.element}>· {m.element}</span>{/if}
            <div class="text-base-content/40 mt-0.5" title={m.summary}>
              {#each m.params as p, i}<span class="text-info/70">{p}</span>{i < m.params.length - 1 ? ' ' : ''}{/each}
              {#if m.params.length === 0}<span class="text-base-content/20">no free param</span>{/if}
            </div>
          </div>
          <div class="text-right whitespace-nowrap text-base-content/40">
            {#each m.signals as s}
              <span class="badge badge-xs badge-outline ml-1"
                    class:badge-warning={missing.includes(s)}
                    title={missing.includes(s) ? 'required signal not wired' : ''}>
                ← {s}{#if missing.includes(s)} ⚠{/if}
              </span>
            {/each}
          </div>
        </div>
      {/each}
    </div>

    <!-- Footer: required signals + identifiability -->
    <div class="border-t border-base-300 mt-2 pt-1.5 text-xs text-base-content/40">
      <div class="flex flex-wrap items-center gap-1">
        <span class="text-base-content/30">needs:</span>
        {#each required as s}
          <span class="badge badge-xs"
                class:badge-ghost={!missing.includes(s)}
                class:badge-warning={missing.includes(s)}>{s}</span>
        {/each}
      </div>
      {#if warning}
        <div class="alert alert-warning text-xs mt-2 py-1.5 px-2">
          <span>⚠ {warning}</span>
        </div>
      {/if}
    </div>
  {/if}
</div>
