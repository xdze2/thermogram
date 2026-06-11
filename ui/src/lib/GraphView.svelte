<script>
	import dagre from 'dagre';

	/** @type {{ model: object, selected: object|null, onselect: function, onaddedge: function, groups?: string[][] }} */
	let { model, selected, onselect, onaddedge, groups = [] } = $props();

	// Group colors — one hue per non-singleton group
	const GROUP_COLORS = ['#f97316', '#22d3ee', '#a78bfa', '#4ade80', '#fb7185'];

	// node_id → { color, index } for resistance nodes in non-singleton groups
	const groupInfo = $derived.by(() => {
		const info = {};
		let colorIdx = 0;
		for (const g of groups) {
			if (g.length <= 1) continue;
			const color = GROUP_COLORS[colorIdx % GROUP_COLORS.length];
			colorIdx++;
			for (const key of g) {
				const nodeId = key.split('.')[0];
				info[nodeId] = { color, size: g.length };
			}
		}
		return info;
	});

	const NODE_W = 160;
	const NODE_H = 50;
	const MARGIN = 40;

	// ── wiring mode ──────────────────────────────────────────────────────────
	// wiringFrom: node id that was selected when 'W' was pressed
	let wiringFrom = $state(null);

	function enterWiring() {
		if (selected?.kind && selected.kind !== 'edge') wiringFrom = selected.id;
	}

	function cancelWiring() { wiringFrom = null; }

	function handleNodeClick(kind, id) {
		if (wiringFrom !== null) {
			if (id !== wiringFrom) onaddedge(wiringFrom, id);
			wiringFrom = null;
		} else {
			onselect(selected?.kind === kind && selected?.id === id ? null : { kind, id });
		}
	}

	function handleKeyDown(e) {
		if (e.key === 'w' || e.key === 'W') {
			if (wiringFrom) cancelWiring();
			else enterWiring();
		}
		if (e.key === 'Escape') cancelWiring();
	}

	// ── layout ───────────────────────────────────────────────────────────────
	const layout = $derived.by(() => {
		const g = new dagre.graphlib.Graph();
		g.setGraph({ rankdir: 'TB', nodesep: 60, ranksep: 100 });
		g.setDefaultEdgeLabel(() => ({}));

		for (const n of model.nodes ?? []) {
			g.setNode(n.id, { width: NODE_W, height: NODE_H });
		}

		for (const e of model.edges ?? []) {
			g.setEdge(e.from, e.to);
		}

		dagre.layout(g);

		const positions = {};
		for (const id of g.nodes()) {
			positions[id] = g.node(id);
		}

		let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
		for (const p of Object.values(positions)) {
			minX = Math.min(minX, p.x - NODE_W / 2);
			minY = Math.min(minY, p.y - NODE_H / 2);
			maxX = Math.max(maxX, p.x + NODE_W / 2);
			maxY = Math.max(maxY, p.y + NODE_H / 2);
		}
		const vbX = minX - MARGIN;
		const vbY = minY - MARGIN;
		const vbW = maxX - minX + MARGIN * 2;
		const vbH = maxY - minY + MARGIN * 2;

		return { positions, viewBox: `${vbX} ${vbY} ${vbW} ${vbH}` };
	});

	// ── edge path helper ─────────────────────────────────────────────────────
	function edgePath(fromId, toId) {
		const f = layout.positions[fromId];
		const t = layout.positions[toId];
		if (!f || !t) return '';
		const mx = (f.x + t.x) / 2;
		return `M ${f.x} ${f.y} C ${mx} ${f.y}, ${mx} ${t.y}, ${t.x} ${t.y}`;
	}

	function isEdgeSelected(e) {
		return selected?.kind === 'edge' && selected.from === e.from && selected.to === e.to;
	}

	function selEdge(e) {
		if (isEdgeSelected(e)) onselect(null);
		else onselect({ kind: 'edge', from: e.from, to: e.to });
	}
</script>

<svelte:window onkeydown={handleKeyDown} />

<div class="graph-wrap" class:wiring={wiringFrom !== null}>
	{#if wiringFrom !== null}
		<div class="wiring-banner">
			Wiring from <strong>{wiringFrom}</strong> — click target node &nbsp;·&nbsp; <kbd>Esc</kbd> to cancel
		</div>
	{/if}

	<svg
		class="graph"
		viewBox={layout.viewBox}
		preserveAspectRatio="xMidYMid meet"
		xmlns="http://www.w3.org/2000/svg"
	>
		<!-- wire edges -->
		{#each model.edges ?? [] as e}
			{@const sel = isEdgeSelected(e)}
			<!-- visible stroke -->
			<path
				d={edgePath(e.from, e.to)}
				fill="none"
				stroke={sel ? '#f59e0b' : '#334155'}
				stroke-width={sel ? 2.5 : 2}
			/>
			<!-- fat invisible hit area -->
			<path
				d={edgePath(e.from, e.to)}
				fill="none"
				stroke="transparent"
				stroke-width="14"
				style="cursor:pointer"
				onclick={() => selEdge(e)}
				role="button"
				tabindex="0"
				aria-label={`wire ${e.from} → ${e.to}`}
				onkeydown={(ev) => ev.key === 'Enter' && selEdge(e)}
			/>
		{/each}

		<!-- nodes -->
		{#each model.nodes ?? [] as n}
			{@const p = layout.positions[n.id]}
			{@const x = p?.x - NODE_W / 2}
			{@const y = p?.y - NODE_H / 2}
			{@const selNode = selected?.kind === n.kind && selected?.id === n.id}
			{@const isWiringSource = wiringFrom === n.id}
			{@const isWiringTarget = wiringFrom !== null && wiringFrom !== n.id}

			<g
				transform={`translate(${x},${y})`}
				style="cursor:{wiringFrom !== null && wiringFrom !== n.id ? 'crosshair' : 'pointer'}"
				onclick={() => handleNodeClick(n.kind, n.id)}
				role="button"
				tabindex="0"
				aria-label={n.label ?? n.id}
				onkeydown={(e) => e.key === 'Enter' && handleNodeClick(n.kind, n.id)}
			>
				{#if n.kind === 'mass'}
					<rect
						width={NODE_W} height={NODE_H} rx="8"
						fill={isWiringSource ? '#3b1f00' : selNode ? '#312e81' : '#1e1b4b'}
						stroke={isWiringSource ? '#f59e0b' : selNode ? '#818cf8' : isWiringTarget ? '#475569' : '#6366f1'}
						stroke-width={isWiringSource || selNode ? 2.5 : 1.5}
						stroke-dasharray={isWiringSource ? '5 3' : 'none'}
					/>
					<text x={NODE_W/2} y={NODE_H/2 - 5} text-anchor="middle" class="node-label" fill="#e0e7ff">{n.label ?? n.id}</text>
					<text x={NODE_W/2} y={NODE_H/2 + 12} text-anchor="middle" class="node-sub" fill="#a5b4fc">
						{`C = ${n.C.toExponential(1)} J/K`}
					</text>

				{:else if n.kind === 'boundary'}
					<rect
						width={NODE_W} height={NODE_H} rx="4"
						fill={isWiringSource ? '#3b1f00' : selNode ? '#1c1917' : '#0c0a09'}
						stroke={isWiringSource ? '#f59e0b' : selNode ? '#a3e635' : isWiringTarget ? '#475569' : '#65a30d'}
						stroke-width={isWiringSource || selNode ? 2.5 : 1.5}
						stroke-dasharray={isWiringSource ? '5 3' : '6 3'}
					/>
					<text x={NODE_W/2} y={NODE_H/2 - 5} text-anchor="middle" class="node-label" fill="#ecfccb">{n.label ?? n.id}</text>
					<text x={NODE_W/2} y={NODE_H/2 + 12} text-anchor="middle" class="node-sub" fill="#bef264">
						{typeof n.T_source === 'number' ? `${n.T_source} °C` : n.T_source}
					</text>

				{:else if n.kind === 'resistance'}
					{@const gi = groupInfo[n.id]}
					<rect
						width={NODE_W} height={NODE_H} rx="4"
						fill={isWiringSource ? '#3b1f00' : selNode ? '#1e1a2e' : '#0f0d1a'}
						stroke={isWiringSource ? '#f59e0b' : selNode ? '#818cf8' : isWiringTarget ? '#475569' : gi ? gi.color : '#6366f1'}
						stroke-width={isWiringSource || selNode ? 2.5 : gi ? 2 : 1.5}
						stroke-dasharray={isWiringSource ? '5 3' : 'none'}
					/>
					{@const zx = NODE_W / 2}
					{@const zy = NODE_H / 2 - 4}
					{@const zw = 40}
					{@const zh = 7}
					<text x={NODE_W/2} y={NODE_H/2 - 17} text-anchor="middle" class="node-label" fill={selNode ? '#c7d2fe' : '#a5b4fc'}>{n.label ?? n.id}</text>
					<polyline
						points={`
							${zx - zw/2},${zy}
							${zx - zw/2 + zw/10},${zy - zh}
							${zx - zw/2 + 3*zw/10},${zy + zh}
							${zx - zw/2 + 5*zw/10},${zy - zh}
							${zx - zw/2 + 7*zw/10},${zy + zh}
							${zx - zw/2 + 9*zw/10},${zy - zh}
							${zx + zw/2},${zy}
						`.trim()}
						fill="none"
						stroke={isWiringSource ? '#f59e0b' : selNode ? '#818cf8' : '#6366f1'}
						stroke-width="1.5"
						stroke-linejoin="round"
					/>
					<text x={NODE_W/2} y={NODE_H/2 + 14} text-anchor="middle" class="node-sub" fill={selNode ? '#c7d2fe' : '#a5b4fc'}>
						{n.R} K/W
					</text>
					{#if gi}
						<circle cx={NODE_W - 8} cy={8} r="5" fill={gi.color} />
						<text x={NODE_W - 8} y={8} text-anchor="middle" dominant-baseline="central" class="group-badge-text">{gi.size}</text>
					{/if}

				{:else if n.kind === 'source'}
					<rect
						width={NODE_W} height={NODE_H} rx="22"
						fill={isWiringSource ? '#3b1f00' : selNode ? '#451a03' : '#27130a'}
						stroke={isWiringSource ? '#f59e0b' : selNode ? '#fbbf24' : isWiringTarget ? '#475569' : '#f59e0b'}
						stroke-width={isWiringSource || selNode ? 2.5 : 1.5}
						stroke-dasharray={isWiringSource ? '5 3' : 'none'}
					/>
					<text x={NODE_W/2} y={NODE_H/2 - 5} text-anchor="middle" class="node-label" fill="#fef9c3">{n.label ?? n.id}</text>
					<text x={NODE_W/2} y={NODE_H/2 + 12} text-anchor="middle" class="node-sub" fill="#fde047">
						×{n.gain}
					</text>
				{/if}
			</g>
		{/each}
	</svg>
</div>

<style>
	.graph-wrap {
		flex: 1;
		position: relative;
		min-width: 0;
		min-height: 0;
		height: 100%;
		display: flex;
		flex-direction: column;
	}

	.graph {
		flex: 1;
		width: 100%;
		height: 100%;
		min-height: 0;
		display: block;
		background: #0f172a;
	}

	.wiring .graph {
		cursor: crosshair;
	}

	.wiring-banner {
		position: absolute;
		top: 12px;
		left: 50%;
		transform: translateX(-50%);
		background: #78350f;
		color: #fef3c7;
		border: 1px solid #f59e0b;
		border-radius: 6px;
		padding: 5px 14px;
		font-size: 12px;
		font-family: monospace;
		pointer-events: none;
		z-index: 10;
		white-space: nowrap;
	}

	.wiring-banner kbd {
		background: #451a03;
		border: 1px solid #92400e;
		border-radius: 3px;
		padding: 1px 5px;
		font-family: monospace;
	}

	.node-label {
		font-size: 14px;
		font-weight: 600;
		font-family: 'Inter', system-ui, sans-serif;
		pointer-events: none;
	}

	.node-sub {
		font-size: 12px;
		font-family: monospace;
		pointer-events: none;
	}

	.group-badge-text {
		font-size: 7px;
		font-weight: 700;
		fill: #0f172a;
		pointer-events: none;
	}
</style>
