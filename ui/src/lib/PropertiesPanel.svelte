<script>
  /**
   * Props:
   *   selected: { kind: 'mass'|'boundary'|'source'|'resistance', id: string }
   *           | { kind: 'edge', from: string, to: string }
   *           | null
   *   model: the full model object (read-only here)
   *   onpatch: (kind, id, patch) => void
   *   onadd: (kind) => void
   *   ondelete: (kind, id) => void
   *   ondeleteedge: (from, to) => void
   */
  let { selected, model, onpatch, onadd, ondelete, ondeleteedge } = $props();

  // ── signal autocomplete ───────────────────────────────────────────────────
  const API = '';
  let signals = $state([]);
  let signalsError = $state(false);

  async function loadSignals() {
    try {
      const res = await fetch(`${API}/signals`);
      if (!res.ok) throw new Error(res.statusText);
      signals = await res.json();
      signalsError = false;
    } catch {
      signalsError = true;
    }
  }

  $effect(() => {
    loadSignals();
  });

  const isEdge = $derived(selected?.kind === "edge");

  const item = $derived.by(() => {
    if (!selected || isEdge) return null;
    return (
      (model.nodes ?? []).find(
        (n) => n.id === selected.id && n.kind === selected.kind,
      ) ?? null
    );
  });

  function commit(field, value) {
    onpatch(selected.kind, selected.id, { [field]: value });
  }

  function commitR(value) {
    const num = parseFloat(value);
    if (!isNaN(num) && num > 0) onpatch(selected.kind, selected.id, { R: num });
  }

  function commitC(value) {
    const num = parseFloat(value);
    if (!isNaN(num) && num > 0) onpatch(selected.kind, selected.id, { C: num });
  }

  function commitTSource(value) {
    const num = parseFloat(value);
    onpatch(selected.kind, selected.id, { T_source: isNaN(num) ? value : num });
  }

  function nodeName(id) {
    return (model.nodes ?? []).find((n) => n.id === id)?.label ?? id;
  }
</script>

<aside class="panel">
  {#if !selected}
    {#if model?.notes}
      <p class="model-notes">{model.notes}</p>
    {/if}
    <p class="hint">
      Click a node or wire to inspect it.<br />Select a node then press
      <kbd>W</kbd> to wire.
    </p>
  {:else if isEdge}
    <!-- ── edge selected ── -->
    <div class="header">
      <span class="kind-badge kind-edge">wire</span>
      <button
        class="del-btn"
        onclick={() => ondeleteedge(selected.from, selected.to)}>Delete</button
      >
    </div>
    <div class="fields">
      <div class="edge-display">
        <span class="edge-node">{nodeName(selected.from)}</span>
        <span class="edge-arrow">→</span>
        <span class="edge-node">{nodeName(selected.to)}</span>
      </div>
      <p class="edge-ids">{selected.from} → {selected.to}</p>
    </div>
  {:else if item}
    <!-- ── node selected ── -->
    <div class="header">
      <span class="kind-badge kind-{selected.kind}">{selected.kind}</span>
      <button
        class="del-btn"
        onclick={() => ondelete(selected.kind, selected.id)}>Delete</button
      >
    </div>

    <div class="fields">
      <label>
        <span>id</span>
        <input type="text" value={item.id} disabled />
      </label>

      <label>
        <span>label</span>
        <input
          type="text"
          value={item.label ?? ""}
          oninput={(e) => commit("label", e.target.value)}
        />
      </label>

      {#if selected.kind === "mass"}
        <label>
          <span>C (J/K)</span>
          <input
            type="number"
            value={item.C}
            min="1"
            oninput={(e) => commitC(e.target.value)}
          />
        </label>
      {:else if selected.kind === "boundary"}
        <label>
          <span
            >T_source {#if signalsError}<span
                class="sig-warn"
                title="Cannot reach API">⚠</span
              >{/if}</span
          >
          <input
            type="text"
            list="signal-list"
            value={String(item.T_source ?? "")}
            oninput={(e) => commitTSource(e.target.value)}
            placeholder="measurement/field?tag=val or 12.0"
          />
        </label>
      {:else if selected.kind === "source"}
        <label>
          <span
            >signal {#if signalsError}<span
                class="sig-warn"
                title="Cannot reach API">⚠</span
              >{/if}</span
          >
          <input
            type="text"
            list="signal-list"
            value={item.signal ?? ""}
            oninput={(e) => commit("signal", e.target.value)}
            placeholder="measurement/field?tag=val"
          />
        </label>
        <label>
          <span>gain</span>
          <input
            type="number"
            value={item.gain ?? 1}
            min="0"
            step="0.1"
            oninput={(e) => commit("gain", parseFloat(e.target.value) || 1)}
          />
        </label>
      {:else if selected.kind === "resistance"}
        <label>
          <span>R (K/W)</span>
          <input
            type="number"
            value={item.R}
            min="0.001"
            step="0.01"
            oninput={(e) => commitR(e.target.value)}
          />
        </label>
      {/if}
    </div>

    <!-- wires connected to this node -->
    <div class="wires-section">
      <p class="section-title">Connected wires</p>
      {#each (model.edges ?? []).filter((e) => e.from === selected.id || e.to === selected.id) as e}
        <div class="wire-row">
          <span class="wire-end">{e.from}</span>
          <span class="wire-arrow">→</span>
          <span class="wire-end">{e.to}</span>
          <button
            class="wire-del"
            onclick={() => ondeleteedge(e.from, e.to)}
            title="Delete wire">×</button
          >
        </div>
      {/each}
      {#if (model.edges ?? []).filter((e) => e.from === selected.id || e.to === selected.id).length === 0}
        <p class="no-wires">no wires — press <kbd>W</kbd> to add</p>
      {/if}
    </div>
  {/if}

  <datalist id="signal-list">
    {#each signals as s}
      <option value={s}></option>
    {/each}
  </datalist>

  <div class="add-section">
    <p class="section-title">Add node</p>
    <button onclick={() => onadd("mass")}>+ Mass</button>
    <button onclick={() => onadd("boundary")}>+ Boundary</button>
    <button onclick={() => onadd("source")}>+ Source</button>
    <button onclick={() => onadd("resistance")}>+ Resistance</button>
  </div>
</aside>

<style>
  .panel {
    width: 220px;
    flex-shrink: 0;
    background: #1e293b;
    color: #cbd5e1;
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    border-right: 1px solid #334155;
  }

  .model-notes {
    padding: 12px 14px 0;
    font-size: 12px;
    color: #9eb6d8;
    margin: 0;
    line-height: 1.5;
    font-style: italic;
    border-bottom: 1px solid #1e293b;
  }

  .hint {
    padding: 16px;
    font-size: 12px;
    color: #94a3b8;
    margin: 0;
    flex: 1;
    line-height: 1.6;
  }

  .hint kbd {
    background: #334155;
    border: 1px solid #475569;
    border-radius: 3px;
    padding: 1px 5px;
    font-family: monospace;
    font-size: 11px;
    color: #94a3b8;
  }

  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 14px 8px;
    border-bottom: 1px solid #334155;
  }

  .kind-badge {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    padding: 2px 8px;
    border-radius: 4px;
  }
  .kind-mass {
    background: #312e81;
    color: #a5b4fc;
  }
  .kind-boundary {
    background: #14532d;
    color: #86efac;
  }
  .kind-source {
    background: #451a03;
    color: #fcd34d;
  }
  .kind-resistance {
    background: #1e1b4b;
    color: #818cf8;
  }
  .kind-edge {
    background: #422006;
    color: #fde68a;
  }

  .del-btn {
    background: transparent;
    border: 1px solid #ef4444;
    color: #ef4444;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    cursor: pointer;
  }
  .del-btn:hover {
    background: #7f1d1d;
  }

  .fields {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 12px 14px;
  }

  /* edge display */
  .edge-display {
    display: flex;
    align-items: center;
    gap: 6px;
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 4px;
    padding: 8px 10px;
  }
  .edge-node {
    font-size: 12px;
    font-family: monospace;
    color: #e2e8f0;
  }
  .edge-arrow {
    color: #f59e0b;
    font-size: 14px;
  }
  .edge-ids {
    font-size: 10px;
    font-family: monospace;
    color: #94a3b8;
    margin: 0;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  label > span {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #94a3b8;
  }

  input,
  select {
    background: #0f172a;
    color: #e2e8f0;
    border: 1px solid #334155;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
    font-family: monospace;
    width: 100%;
    box-sizing: border-box;
  }
  input:focus,
  select:focus {
    outline: none;
    border-color: #6366f1;
  }
  input:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .wires-section {
    padding: 8px 14px 12px;
    border-top: 1px solid #334155;
  }

  .wire-row {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    font-family: monospace;
    color: #94a3b8;
    padding: 3px 0;
  }

  .wire-end {
    color: #cbd5e1;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .wire-arrow {
    color: #94a3b8;
    flex-shrink: 0;
  }

  .wire-del {
    background: transparent;
    border: none;
    color: #94a3b8;
    font-size: 14px;
    line-height: 1;
    cursor: pointer;
    padding: 0 2px;
    flex-shrink: 0;
  }
  .wire-del:hover {
    color: #ef4444;
  }

  .no-wires {
    font-size: 11px;
    color: #94a3b8;
    font-family: monospace;
    margin: 4px 0 0;
  }
  .no-wires kbd {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 3px;
    padding: 0px 4px;
    font-family: monospace;
  }

  .add-section {
    padding: 12px 14px;
    border-top: 1px solid #334155;
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-top: auto;
  }

  .section-title {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #94a3b8;
    margin: 0 0 2px;
  }

  button {
    background: #334155;
    color: #cbd5e1;
    border: 1px solid #475569;
    border-radius: 4px;
    padding: 5px 10px;
    font-size: 12px;
    cursor: pointer;
    text-align: left;
  }
  button:hover {
    background: #475569;
  }

  .sig-warn {
    color: #f59e0b;
    font-size: 10px;
  }
</style>
