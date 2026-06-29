<script>
  /**
   * TopologySvg — hand-rolled star topology SVG.
   *
   * Layout:
   *   - T_room (room node) at center
   *   - state nodes (hidden thermal states) in an inner ring
   *   - boundary nodes (T_ext, G_sol, …) around the outer perimeter
   *
   * Receives `graph` prop: { nodes: [{id, kind}], edges: [{from, to, module_id}] }
   * Falls back gracefully when graph is null/empty.
   */

  /** @type {{ nodes: Array<{id: string, kind: string}>, edges: Array<{from: string, to: string, module_id: string}> } | null} */
  export let graph = null;

  // ---------------------------------------------------------------------------
  // Layout computation
  // ---------------------------------------------------------------------------

  const WIDTH  = 480;
  const HEIGHT = 340;
  const CX = WIDTH / 2;
  const CY = HEIGHT / 2;

  const R_OUTER = 130;  // boundary nodes radius
  const R_INNER = 65;   // state nodes radius

  const NODE_R = {
    room:     22,
    state:    16,
    boundary: 16,
  };

  const NODE_FILL = {
    room:     'oklch(65% 0.15 250)',  // blue-ish
    state:    'oklch(72% 0.12 45)',   // orange-ish
    boundary: 'oklch(70% 0.10 150)', // green-ish
  };

  const NODE_STROKE = {
    room:     'oklch(45% 0.15 250)',
    state:    'oklch(50% 0.12 45)',
    boundary: 'oklch(50% 0.10 150)',
  };

  $: layout = computeLayout(graph);

  function computeLayout(g) {
    if (!g?.nodes?.length) return null;

    const roomNode     = g.nodes.find(n => n.kind === 'room');
    const stateNodes   = g.nodes.filter(n => n.kind === 'state');
    const boundaryNodes = g.nodes.filter(n => n.kind === 'boundary');

    const positions = {};

    // Room at center
    if (roomNode) {
      positions[roomNode.id] = { x: CX, y: CY };
    }

    // State nodes in inner ring
    stateNodes.forEach((n, i) => {
      const count = stateNodes.length || 1;
      const angle = (2 * Math.PI * i) / count - Math.PI / 2;
      positions[n.id] = {
        x: CX + R_INNER * Math.cos(angle),
        y: CY + R_INNER * Math.sin(angle),
      };
    });

    // Boundary nodes in outer ring
    boundaryNodes.forEach((n, i) => {
      const count = boundaryNodes.length || 1;
      const angle = (2 * Math.PI * i) / count - Math.PI / 2;
      positions[n.id] = {
        x: CX + R_OUTER * Math.cos(angle),
        y: CY + R_OUTER * Math.sin(angle),
      };
    });

    return { positions, nodes: g.nodes, edges: g.edges ?? [] };
  }

  function edgeKey(edge, i) {
    return `${edge.from}->${edge.to}-${edge.module_id}-${i}`;
  }

  // Deduplicate edges that share the same from/to (keep unique module label)
  $: deduplicatedEdges = dedupeEdges(graph?.edges ?? []);

  function dedupeEdges(edges) {
    const seen = {};
    return edges.filter(e => {
      const k = `${e.from}--${e.to}`;
      if (seen[k]) return false;
      seen[k] = true;
      return true;
    });
  }
</script>

{#if !graph?.nodes?.length}
  <div class="border border-base-300 rounded-lg p-6 text-center text-base-content/50 text-sm">
    No topology data. Add modules and elements to see the star graph.
  </div>
{:else if !layout}
  <div class="border border-base-300 rounded-lg p-6 text-center text-base-content/50 text-sm">
    Computing layout…
  </div>
{:else}
  <div class="overflow-x-auto">
    <svg
      viewBox="0 0 {WIDTH} {HEIGHT}"
      width="100%"
      style="max-width: {WIDTH}px;"
      role="img"
      aria-label="Star topology graph showing thermal nodes and connections"
    >
      <!-- Edges (drawn first, behind nodes) -->
      {#each deduplicatedEdges as edge}
        {@const from = layout.positions[edge.from]}
        {@const to   = layout.positions[edge.to]}
        {#if from && to}
          <line
            x1={from.x} y1={from.y}
            x2={to.x}   y2={to.y}
            stroke="oklch(70% 0 0)"
            stroke-width="1.5"
            opacity="0.5"
          />
        {/if}
      {/each}

      <!-- Nodes -->
      {#each layout.nodes as node}
        {@const pos = layout.positions[node.id]}
        {#if pos}
          {@const r    = NODE_R[node.kind] ?? 14}
          {@const fill  = NODE_FILL[node.kind]  ?? '#aaa'}
          {@const stroke= NODE_STROKE[node.kind] ?? '#666'}
          <g>
            <circle
              cx={pos.x} cy={pos.y} r={r}
              fill={fill}
              stroke={stroke}
              stroke-width="1.5"
            />
            <text
              x={pos.x}
              y={pos.y + r + 12}
              text-anchor="middle"
              font-size="11"
              fill="oklch(30% 0 0)"
              font-family="ui-monospace, monospace"
            >
              {node.id}
            </text>
            {#if node.kind === 'room'}
              <!-- Label inside the room circle -->
              <text
                x={pos.x}
                y={pos.y + 4}
                text-anchor="middle"
                font-size="10"
                font-weight="bold"
                fill="white"
                font-family="system-ui, sans-serif"
              >
                room
              </text>
            {/if}
          </g>
        {/if}
      {/each}

      <!-- Legend -->
      <g transform="translate(8, {HEIGHT - 56})">
        <circle cx="8" cy="6" r="6" fill={NODE_FILL.room}     stroke={NODE_STROKE.room}     stroke-width="1"/>
        <text x="18" y="10" font-size="10" fill="oklch(40% 0 0)">room</text>
        <circle cx="8" cy="22" r="6" fill={NODE_FILL.state}    stroke={NODE_STROKE.state}    stroke-width="1"/>
        <text x="18" y="26" font-size="10" fill="oklch(40% 0 0)">state (hidden)</text>
        <circle cx="8" cy="38" r="6" fill={NODE_FILL.boundary} stroke={NODE_STROKE.boundary} stroke-width="1"/>
        <text x="18" y="42" font-size="10" fill="oklch(40% 0 0)">boundary</text>
      </g>
    </svg>
  </div>
{/if}
