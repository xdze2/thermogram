<script>
  /**
   * SignalBindingPanel — renders binding controls for:
   *   - Required signals (inputs): boundary conditions the ODE consumes.
   *   - Sensors (outputs): observed quantities the fit minimises against.
   *
   * Both use the same InfluxDB binding picker pattern.
   */
  import {
    requiredSignals, setSignalBinding,
    sensors, addSensor, removeSensor, setSensorBinding,
  } from '../stores/model.js';
  import { fetchInfluxSignals } from './api.js';

  // ---------------------------------------------------------------------------
  // InfluxDB signal catalogue — fetched once, lazily, then cached in module scope
  // so navigating away and back doesn't re-fetch.
  // ---------------------------------------------------------------------------

  /** @type {string[] | null} null = not yet fetched */
  let influxSignals = null;
  let influxLoading = false;
  let influxError = '';   // '503:…' | 'unreachable' | '' when ok

  async function ensureInfluxSignals() {
    if (influxSignals !== null || influxLoading) return;
    influxLoading = true;
    influxError = '';
    try {
      influxSignals = await fetchInfluxSignals();
    } catch (err) {
      // 503 is surfaced as a thrown Error with the detail string.
      influxError = err.message ?? String(err);
      // Keep influxSignals null so user can retry.
    } finally {
      influxLoading = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Per-signal picker state
  // ---------------------------------------------------------------------------

  // ---------------------------------------------------------------------------
  // Unified picker state — key is "sig:<name>" or "sen:<id>"
  // ---------------------------------------------------------------------------

  /** Which item currently has its picker open. @type {string | null} */
  let openPickerFor = null;

  /** Draft input values keyed by picker key. @type {Record<string,string>} */
  let draftValues = {};

  /** Per-key errors from the last PUT. @type {Record<string,string>} */
  let bindingErrors = {};

  /** Per-key in-flight flag. @type {Record<string,boolean>} */
  let bindingBusy = {};

  function openPicker(key, currentBinding) {
    openPickerFor = key;
    draftValues[key] = currentBinding ?? '';
    bindingErrors[key] = '';
    ensureInfluxSignals();
  }

  function closePicker() {
    openPickerFor = null;
  }

  async function applyBinding(key, commitFn) {
    const val = (draftValues[key] ?? '').trim();
    if (!val) {
      bindingErrors[key] = 'Enter a signal string or pick from the list.';
      return;
    }
    bindingErrors[key] = '';
    bindingBusy[key] = true;
    try {
      await commitFn(val);
      closePicker();
    } catch (err) {
      bindingErrors[key] = err.message ?? String(err);
    } finally {
      bindingBusy[key] = false;
    }
  }

  async function clearBinding(key, clearFn) {
    bindingErrors[key] = '';
    bindingBusy[key] = true;
    try {
      await clearFn();
    } catch (err) {
      bindingErrors[key] = err.message ?? String(err);
    } finally {
      bindingBusy[key] = false;
    }
  }

  function handleKeydown(e, key, commitFn) {
    if (e.key === 'Enter') applyBinding(key, commitFn);
    if (e.key === 'Escape') closePicker();
  }

  function datalistId(key) {
    return `influx-signals-${key.replace(/[^a-zA-Z0-9]/g, '_')}`;
  }

  // ---------------------------------------------------------------------------
  // Sensor add state
  // ---------------------------------------------------------------------------

  let addingSensor = false;
  let sensorAddError = '';
  let sensorAddBusy = false;

  async function submitAddSensor() {
    sensorAddError = '';
    sensorAddBusy = true;
    try {
      await addSensor('T_room', 'T_indoor');
      addingSensor = false;
    } catch (err) {
      sensorAddError = err.message ?? String(err);
    } finally {
      sensorAddBusy = false;
    }
  }

  async function handleRemoveSensor(sensorId) {
    try {
      await removeSensor(sensorId);
    } catch (_) {}
  }
</script>

<!-- ── Required signals (inputs) ─────────────────────────────────────── -->
<div class="mb-4">
  <div class="text-xs font-semibold text-base-content/50 uppercase tracking-wide mb-2">Inputs</div>
  {#if $requiredSignals.length === 0}
    <p class="text-sm text-base-content/40">No signals required yet — add elements with boundaries set.</p>
  {:else}
    <div class="space-y-3">
      {#each $requiredSignals as sig (sig.name)}
        {@const key = `sig:${sig.name}`}
        {@const isOpen = openPickerFor === key}
        {@const isBound = !!sig.binding}
        {@const isBusy = !!bindingBusy[key]}
        {@const hasErr = !!bindingErrors[key]}

        <div class="flex flex-col gap-1">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="font-mono text-sm font-medium">{sig.name}</span>
            <span class="badge badge-ghost badge-xs">{sig.kind}</span>
            {#if sig.meta?.orientation}
              <span class="badge badge-ghost badge-xs">{sig.meta.orientation}</span>
            {/if}

            {#if isBusy}
              <span class="loading loading-spinner loading-xs text-primary"></span>
            {:else if isBound && !isOpen}
              <span class="badge badge-success badge-sm gap-1 max-w-[22ch] truncate" title={sig.binding}>
                <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414L8.414 14l-4.121-4.121a1 1 0 011.414-1.414L8.414 11.172l6.879-6.879a1 1 0 011.414 0z" clip-rule="evenodd"/>
                </svg>
                <span class="truncate font-mono text-xs">{sig.binding}</span>
              </span>
              <button class="btn btn-ghost btn-xs text-error" onclick={() => clearBinding(key, () => setSignalBinding(sig.name, null))} disabled={isBusy}>&times; clear</button>
              <button class="btn btn-ghost btn-xs" onclick={() => openPicker(key, sig.binding)}>edit</button>
            {:else if !isBound && !isOpen}
              <span class="badge badge-warning badge-sm gap-1">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
                </svg>
                unbound
              </span>
              <button class="btn btn-outline btn-xs btn-primary" onclick={() => openPicker(key, sig.binding)}>Bind…</button>
            {/if}
          </div>

          {#if isOpen}
            {@render pickerBlock(key, isBusy, hasErr, (val) => setSignalBinding(sig.name, val))}
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<!-- ── Sensors (outputs) ──────────────────────────────────────────────── -->
<div>
  <div class="flex items-center justify-between mb-2">
    <div class="text-xs font-semibold text-base-content/50 uppercase tracking-wide">Sensors</div>
    {#if !addingSensor}
      <button class="btn btn-ghost btn-xs btn-primary" onclick={() => { addingSensor = true; sensorAddError = ''; }}>
        + Add sensor
      </button>
    {/if}
  </div>

  {#if addingSensor}
    <div class="flex items-center gap-2 mb-3 pl-2 border-l-2 border-primary/30 ml-1">
      <span class="text-xs text-base-content/60">Observes <span class="font-mono">T_room</span> (indoor temperature)</span>
      <button class="btn btn-primary btn-xs" onclick={submitAddSensor} disabled={sensorAddBusy}>
        {#if sensorAddBusy}<span class="loading loading-spinner loading-xs"></span>{/if}
        Add
      </button>
      <button class="btn btn-ghost btn-xs" onclick={() => addingSensor = false} disabled={sensorAddBusy}>Cancel</button>
      {#if sensorAddError}<span class="text-error text-xs">{sensorAddError}</span>{/if}
    </div>
  {/if}

  {#if $sensors.length === 0 && !addingSensor}
    <p class="text-sm text-base-content/40">No sensors yet — add one to enable parameter fitting.</p>
  {:else}
    <div class="space-y-3">
      {#each $sensors as sen (sen.id)}
        {@const key = `sen:${sen.id}`}
        {@const isOpen = openPickerFor === key}
        {@const isBound = !!sen.binding}
        {@const isBusy = !!bindingBusy[key]}
        {@const hasErr = !!bindingErrors[key]}

        <div class="flex flex-col gap-1">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="font-mono text-sm font-medium">{sen.name}</span>
            <span class="badge badge-ghost badge-xs">temperature</span>
            <span class="badge badge-outline badge-xs text-base-content/50">observes {sen.state}</span>

            {#if isBusy}
              <span class="loading loading-spinner loading-xs text-primary"></span>
            {:else if isBound && !isOpen}
              <span class="badge badge-success badge-sm gap-1 max-w-[22ch] truncate" title={sen.binding}>
                <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414L8.414 14l-4.121-4.121a1 1 0 011.414-1.414L8.414 11.172l6.879-6.879a1 1 0 011.414 0z" clip-rule="evenodd"/>
                </svg>
                <span class="truncate font-mono text-xs">{sen.binding}</span>
              </span>
              <button class="btn btn-ghost btn-xs text-error" onclick={() => clearBinding(key, () => setSensorBinding(sen.id, null))} disabled={isBusy}>&times; clear</button>
              <button class="btn btn-ghost btn-xs" onclick={() => openPicker(key, sen.binding)}>edit</button>
            {:else if !isBound && !isOpen}
              <span class="badge badge-warning badge-sm gap-1">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
                </svg>
                unbound
              </span>
              <button class="btn btn-outline btn-xs btn-primary" onclick={() => openPicker(key, sen.binding)}>Bind…</button>
            {/if}

            <button
              class="btn btn-ghost btn-xs text-error ml-auto"
              aria-label="Remove sensor {sen.name}"
              onclick={() => handleRemoveSensor(sen.id)}
              disabled={isBusy}
            >Delete</button>
          </div>

          {#if isOpen}
            {@render pickerBlock(key, isBusy, hasErr, (val) => setSensorBinding(sen.id, val))}
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<!-- ── Shared picker snippet ──────────────────────────────────────────── -->
{#snippet pickerBlock(key, isBusy, hasErr, commitFn)}
  <div class="flex flex-col gap-2 pl-2 border-l-2 border-primary/30 ml-1">
    {#if influxLoading}
      <div class="flex items-center gap-2 text-xs text-base-content/60">
        <span class="loading loading-spinner loading-xs"></span>
        Loading InfluxDB signals…
      </div>
    {:else if influxError}
      <div role="alert" class="alert alert-warning alert-sm py-1 text-xs">
        <span>InfluxDB unreachable — you can still type a binding string manually.</span>
      </div>
    {/if}

    <div class="flex gap-2 items-center flex-wrap">
      <div class="form-control flex-1 min-w-[16rem]">
        <label class="label py-0" for="picker-{key}">
          <span class="label-text text-xs">
            Binding string
            {#if influxSignals}
              <span class="text-base-content/40">({influxSignals.length} available)</span>
            {/if}
          </span>
        </label>
        <input
          id="picker-{key}"
          type="text"
          class="input input-bordered input-sm font-mono text-xs"
          class:input-error={hasErr}
          list={datalistId(key)}
          placeholder="measurement/field?tag=val"
          bind:value={draftValues[key]}
          onkeydown={(e) => handleKeydown(e, key, commitFn)}
          aria-describedby={hasErr ? `picker-err-${key}` : undefined}
        />
        {#if influxSignals}
          <datalist id={datalistId(key)}>
            {#each influxSignals as option}
              <option value={option}>{option}</option>
            {/each}
          </datalist>
        {/if}
      </div>

      <div class="flex gap-1 items-end pb-0.5">
        <button
          class="btn btn-primary btn-sm"
          onclick={() => applyBinding(key, commitFn)}
          disabled={isBusy || !draftValues[key]?.trim()}
        >
          {#if isBusy}<span class="loading loading-spinner loading-xs"></span>{/if}
          Set
        </button>
        <button class="btn btn-ghost btn-sm" onclick={closePicker} disabled={isBusy}>Cancel</button>
      </div>
    </div>

    {#if hasErr}
      <div id="picker-err-{key}" role="alert" class="text-error text-xs">{bindingErrors[key]}</div>
    {/if}
  </div>
{/snippet}
