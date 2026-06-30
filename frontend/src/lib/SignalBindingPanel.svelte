<script>
  /**
   * SignalBindingPanel — renders binding controls for every required signal
   * returned by the assembly store.
   *
   * Each required signal comes from assembly.required_signals[] and already
   * carries its current binding (string | null). The user can:
   *   - Click "Bind…" to open a picker (input + datalist backed by
   *     GET /api/influx/signals, fetched once then cached).
   *   - Type a binding string freely (backend validates on PUT).
   *   - Click "×" on a bound signal to clear it (PUT with null).
   *
   * All mutations go through setSignalBinding() in model.js, which follows
   * the applyMutation → re-pull invariant so the assembly store (and thus
   * this component) updates automatically.
   */
  import { requiredSignals, setSignalBinding } from '../stores/model.js';
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

  /**
   * Which signal name currently has its picker open.
   * Only one picker open at a time.
   * @type {string | null}
   */
  let openPickerFor = null;

  /** Draft input value while the picker is open. @type {Record<string,string>} */
  let draftValues = {};

  /** Per-signal error from the last PUT. @type {Record<string,string>} */
  let bindingErrors = {};

  /** Per-signal in-flight flag. @type {Record<string,boolean>} */
  let bindingBusy = {};

  function openPicker(sigName, currentBinding) {
    openPickerFor = sigName;
    draftValues[sigName] = currentBinding ?? '';
    bindingErrors[sigName] = '';
    // Lazily load the catalogue on first open.
    ensureInfluxSignals();
  }

  function closePicker() {
    openPickerFor = null;
  }

  async function applyBinding(sigName) {
    const val = (draftValues[sigName] ?? '').trim();
    if (!val) {
      bindingErrors[sigName] = 'Enter a signal string or pick from the list.';
      return;
    }
    bindingErrors[sigName] = '';
    bindingBusy[sigName] = true;
    try {
      await setSignalBinding(sigName, val);
      closePicker();
    } catch (err) {
      // model.js puts transport errors in the global error store; here we also
      // capture validation errors (400) that only concern this signal.
      bindingErrors[sigName] = err.message ?? String(err);
    } finally {
      bindingBusy[sigName] = false;
    }
  }

  async function clearBinding(sigName) {
    bindingErrors[sigName] = '';
    bindingBusy[sigName] = true;
    try {
      await setSignalBinding(sigName, null);
    } catch (err) {
      bindingErrors[sigName] = err.message ?? String(err);
    } finally {
      bindingBusy[sigName] = false;
    }
  }

  function handleKeydown(e, sigName) {
    if (e.key === 'Enter') applyBinding(sigName);
    if (e.key === 'Escape') closePicker();
  }

  // ---------------------------------------------------------------------------
  // Derived: filter catalogue by the current draft value for faster selection.
  // With 113 entries the datalist handles this natively; we also expose a
  // compact filtered count for screenreaders.
  // ---------------------------------------------------------------------------

  /**
   * Build the datalist id for a given signal name — must be a valid HTML id.
   * @param {string} name
   */
  function datalistId(name) {
    return `influx-signals-${name.replace(/[^a-zA-Z0-9]/g, '_')}`;
  }
</script>

{#if $requiredSignals.length === 0}
  <p class="text-sm text-base-content/40">
    No signals required yet — add elements with boundaries set.
  </p>
{:else}
  <div class="space-y-3">
    {#each $requiredSignals as sig (sig.name)}
      {@const isOpen = openPickerFor === sig.name}
      {@const isBound = !!sig.binding}
      {@const isBusy = !!bindingBusy[sig.name]}
      {@const hasErr = !!bindingErrors[sig.name]}

      <div class="flex flex-col gap-1">

        <!-- Signal header row: name / kind badges + bound/unbound indicator -->
        <div class="flex items-center gap-2 flex-wrap">
          <!-- Signal identity -->
          <span class="font-mono text-sm font-medium">{sig.name}</span>
          <span class="badge badge-ghost badge-xs">{sig.kind}</span>
          {#if sig.meta?.orientation}
            <span class="badge badge-ghost badge-xs">{sig.meta.orientation}</span>
          {/if}

          <!-- Bound / unbound state with actions -->
          {#if isBusy}
            <span class="loading loading-spinner loading-xs text-primary"></span>
          {:else if isBound && !isOpen}
            <!-- Bound: show the binding string + clear button -->
            <span
              class="badge badge-success badge-sm gap-1 max-w-[22ch] truncate"
              title={sig.binding}
            >
              <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414L8.414 14l-4.121-4.121a1 1 0 011.414-1.414L8.414 11.172l6.879-6.879a1 1 0 011.414 0z" clip-rule="evenodd"/>
              </svg>
              <span class="truncate font-mono text-xs">{sig.binding}</span>
            </span>
            <button
              class="btn btn-ghost btn-xs text-error"
              aria-label="Clear binding for {sig.name}"
              onclick={() => clearBinding(sig.name)}
              disabled={isBusy}
            >
              &times; clear
            </button>
            <button
              class="btn btn-ghost btn-xs"
              onclick={() => openPicker(sig.name, sig.binding)}
              aria-label="Edit binding for {sig.name}"
            >
              edit
            </button>
          {:else if !isBound && !isOpen}
            <!-- Unbound: show "Bind…" affordance -->
            <span class="badge badge-warning badge-sm gap-1">
              <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
              </svg>
              unbound
            </span>
            <button
              class="btn btn-outline btn-xs btn-primary"
              onclick={() => openPicker(sig.name, sig.binding)}
              aria-label="Bind signal {sig.name} to an InfluxDB source"
            >
              Bind…
            </button>
          {/if}
        </div>

        <!-- Picker (shown when open) -->
        {#if isOpen}
          <div class="flex flex-col gap-2 pl-2 border-l-2 border-primary/30 ml-1">

            <!-- Catalogue status -->
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

            <!-- Combo: native input + datalist for filtering 113 entries -->
            <div class="flex gap-2 items-center flex-wrap">
              <div class="form-control flex-1 min-w-[16rem]">
                <label class="label py-0" for="picker-{sig.name}">
                  <span class="label-text text-xs">
                    Binding string
                    {#if influxSignals}
                      <span class="text-base-content/40">({influxSignals.length} available)</span>
                    {/if}
                  </span>
                </label>
                <input
                  id="picker-{sig.name}"
                  type="text"
                  class="input input-bordered input-sm font-mono text-xs"
                  class:input-error={hasErr}
                  list={datalistId(sig.name)}
                  placeholder="measurement/field?tag=val"
                  bind:value={draftValues[sig.name]}
                  onkeydown={(e) => handleKeydown(e, sig.name)}
                  aria-describedby={hasErr ? `picker-err-${sig.name}` : undefined}
                />
                <!-- Datalist: browser filters options by partial match -->
                {#if influxSignals}
                  <datalist id={datalistId(sig.name)}>
                    {#each influxSignals as option}
                      <option value={option}>{option}</option>
                    {/each}
                  </datalist>
                {/if}
              </div>

              <!-- Action buttons -->
              <div class="flex gap-1 items-end pb-0.5">
                <button
                  class="btn btn-primary btn-sm"
                  onclick={() => applyBinding(sig.name)}
                  disabled={isBusy || !draftValues[sig.name]?.trim()}
                >
                  {#if isBusy}
                    <span class="loading loading-spinner loading-xs"></span>
                  {/if}
                  Set
                </button>
                <button
                  class="btn btn-ghost btn-sm"
                  onclick={closePicker}
                  disabled={isBusy}
                >
                  Cancel
                </button>
              </div>
            </div>

            <!-- Per-signal binding error (e.g. 400 malformed) -->
            {#if hasErr}
              <div
                id="picker-err-{sig.name}"
                role="alert"
                class="text-error text-xs"
              >
                {bindingErrors[sig.name]}
              </div>
            {/if}
          </div>
        {/if}

      </div>
    {/each}
  </div>
{/if}
