<script>
  import { fmt, scaleUnits } from './format.js';

  export let p;

  $: [mu, sigma, unit] = scaleUnits(p.mu, p.sigma, p.unit);
  $: cv = mu > 0 ? (sigma / mu * 100).toFixed(0) : '—';
  $: maxVal = Math.max(...p.contributions.map(c => Math.abs(scaleUnits(c.value, c.sigma ?? 0, p.unit)[0])), 1e-9);
</script>

<div>
  <!-- Header -->
  <div class="flex items-baseline gap-2 mb-1">
    <span class="text-info font-semibold">{p.symbol}</span>
    <span class="text-xs text-base-content/40">{p.name}</span>
    <span class="badge badge-xs badge-ghost">{unit}</span>
  </div>

  <!-- Contributions -->
  {#each p.contributions as c}
    {@const [cVal, cSig] = scaleUnits(c.value, c.sigma ?? 0, p.unit)}
    {@const barPct = Math.min(100, Math.abs(cVal) / maxVal * 100)}
    <div class="grid items-center gap-2 py-0.5 text-xs text-base-content/50"
      style="grid-template-columns: 1fr 100px 80px">
      <span title={c.detail ?? ''}>{c.label ?? ''}</span>
      <span class="text-right tabular-nums">
        +{fmt(cVal)} <span class="text-base-content/30">{c.sigma != null ? `±${fmt(cSig)}` : ''}</span>
      </span>
      <div class="contrib-bar-wrap">
        <div class="contrib-bar" style="width:{barPct.toFixed(1)}%"></div>
      </div>
    </div>
  {/each}

  <!-- Total -->
  <div class="flex items-center gap-3 border-t border-base-300 pt-1 mt-0.5 text-sm">
    <span class="tabular-nums font-medium">= {fmt(mu)} {unit}</span>
    <span class="text-xs text-base-content/40 tabular-nums">± {fmt(sigma)}</span>
    <span class="badge badge-xs badge-ghost text-base-content/30">CV {cv}%</span>
  </div>
</div>
