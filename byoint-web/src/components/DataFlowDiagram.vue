<template>
  <div class="flow-diagram">
    <div v-if="!layout.nodes.length" class="text-muted">No datapulls, enrichments or outputs configured.</div>
    <svg
      v-else
      :viewBox="`0 0 ${VIEW_W} ${layout.height}`"
      class="flow-svg"
      role="img"
      aria-label="Datapulls to enrichments to outputs flow"
      @mouseleave="hovered = null"
    >
      <text
        v-for="col in columns"
        :key="`h-${col.key}`"
        :x="col.x + NODE_W / 2"
        y="18"
        class="col-header"
        text-anchor="middle"
      >{{ col.label }} ({{ col.count }})</text>

      <path
        v-for="edge in layout.edges"
        :key="edge.id"
        :d="edge.d"
        class="flow-edge"
        :class="[`edge-${edge.kind}`, { 'is-dim': isDim(edge.id), 'is-hot': isHot(edge.id) }]"
      />

      <g
        v-for="node in layout.nodes"
        :key="node.id"
        class="flow-node"
        :class="[`node-${node.column}`, { 'is-disabled': !node.enabled, 'is-missing': node.missing, 'is-dim': isDim(node.id), 'is-hot': isHot(node.id) }]"
        :transform="`translate(${node.x}, ${node.y})`"
        @mouseenter="hovered = node.id"
        @click="openNode(node)"
      >
        <title>{{ node.tooltip }}</title>
        <rect :width="NODE_W" :height="NODE_H" rx="8" />
        <rect class="node-accent" width="5" :height="NODE_H" rx="2" />
        <text x="14" :y="NODE_H / 2" dominant-baseline="central" class="node-label">{{ truncate(node.label, 24) }}</text>
        <text v-if="node.meta" :x="NODE_W - 10" :y="NODE_H / 2" dominant-baseline="central" text-anchor="end" class="node-meta">{{ truncate(node.meta, 10) }}</text>
      </g>
    </svg>

    <div v-if="layout.nodes.length" class="flow-legend">
      <span><i class="swatch swatch-datapull"></i>Datapull</span>
      <span><i class="swatch swatch-enrichment"></i>Enrichment</span>
      <span><i class="swatch swatch-output"></i>Output</span>
      <span><i class="swatch swatch-disabled"></i>Disabled / inactive</span>
      <span class="text-muted">Hover a node to trace its path, click to open.</span>
    </div>
  </div>
</template>

<script>
export default {
  name: 'DataFlowDiagram',
  props: {
    datapulls: { type: Array, default: () => [] },
    enrichments: { type: Array, default: () => [] },
    outputs: { type: Array, default: () => [] }
  },
  data() {
    return {
      VIEW_W: 1000,
      NODE_W: 250,
      NODE_H: 34,
      ROW_GAP: 10,
      TOP: 34,
      hovered: null
    }
  },
  computed: {
    columnX() {
      return {
        datapull: 0,
        enrichment: (this.VIEW_W - this.NODE_W) / 2,
        output: this.VIEW_W - this.NODE_W
      }
    },
    graph() {
      const nodes = new Map()
      const addNode = (column, name, extra) => {
        const id = `${column}:${name}`
        if (!nodes.has(id)) nodes.set(id, { id, column, label: name, enabled: true, missing: false, meta: '', ...extra })
        return id
      }

      this.datapulls.forEach(d => addNode('datapull', d.name, {
        enabled: d.active,
        meta: d.source_type,
        tooltip: `Datapull: ${d.name}${d.source_type ? ` (${d.source_type})` : ''}${d.active ? '' : ' — inactive'}`
      }))
      this.enrichments.forEach(e => addNode('enrichment', e.name, {
        enabled: e.enabled,
        meta: e.data_type,
        tooltip: `Enrichment: ${e.name}${e.data_type ? ` on ${e.data_type}` : ''}${e.enabled ? '' : ' — disabled'}`
      }))
      this.outputs.forEach(o => addNode('output', o.name, {
        enabled: o.enabled,
        meta: o.type,
        tooltip: `Output: ${o.name}${o.type ? ` (${o.type})` : ''}${o.enabled ? '' : ' — disabled'}\nSources: ${o.sources.join(', ') || 'none'}`
      }))

      // Each path is datapull -> enrichment (or raw passthrough) -> output (optional).
      const paths = []
      this.datapulls.forEach(d => {
        const dId = `datapull:${d.name}`
        const mids = d.enrichments.length
          ? d.enrichments.map(name => addNode('enrichment', name, { missing: true, enabled: false, tooltip: `Enrichment "${name}" is selected but not defined` }))
          : [addNode('enrichment', '__raw__', { label: 'No enrichment (raw)', tooltip: 'Datapulls feeding outputs without enrichment', raw: true })]
        const outs = this.outputs.filter(o => o.sources.includes(d.name)).map(o => `output:${o.name}`)
        mids.forEach(m => {
          if (outs.length) outs.forEach(o => paths.push([dId, m, o]))
          else paths.push([dId, m])
        })
      })

      const edges = new Map()
      const memberOf = new Map()
      const mark = (id, pathIdx) => {
        if (!memberOf.has(id)) memberOf.set(id, new Set())
        memberOf.get(id).add(pathIdx)
      }
      paths.forEach((p, i) => {
        p.forEach(id => mark(id, i))
        for (let k = 0; k < p.length - 1; k++) {
          const edgeId = `${p[k]}->${p[k + 1]}`
          if (!edges.has(edgeId)) edges.set(edgeId, { id: edgeId, from: p[k], to: p[k + 1] })
          mark(edgeId, i)
        }
      })

      return { nodes, edges: [...edges.values()], memberOf }
    },
    columns() {
      const counts = { datapull: 0, enrichment: 0, output: 0 }
      this.graph.nodes.forEach(n => { if (!n.raw) counts[n.column]++ })
      return [
        { key: 'datapull', label: 'Datapulls', count: counts.datapull, x: this.columnX.datapull },
        { key: 'enrichment', label: 'Enrichments', count: counts.enrichment, x: this.columnX.enrichment },
        { key: 'output', label: 'Outputs', count: counts.output, x: this.columnX.output }
      ]
    },
    layout() {
      const byColumn = { datapull: [], enrichment: [], output: [] }
      this.graph.nodes.forEach(n => byColumn[n.column].push(n))
      // Keep the raw passthrough node at the bottom of the middle column.
      byColumn.enrichment.sort((a, b) => Number(!!a.raw) - Number(!!b.raw))

      const step = this.NODE_H + this.ROW_GAP
      const rows = Math.max(1, ...Object.values(byColumn).map(c => c.length))
      const height = this.TOP + rows * step

      const positioned = new Map()
      Object.entries(byColumn).forEach(([column, list]) => {
        const offset = this.TOP + ((rows - list.length) * step) / 2
        list.forEach((n, i) => positioned.set(n.id, { ...n, x: this.columnX[column], y: offset + i * step }))
      })

      const edges = this.graph.edges.map(e => {
        const a = positioned.get(e.from)
        const b = positioned.get(e.to)
        const x1 = a.x + this.NODE_W
        const y1 = a.y + this.NODE_H / 2
        const x2 = b.x
        const y2 = b.y + this.NODE_H / 2
        const mx = (x1 + x2) / 2
        return { ...e, kind: b.column === 'output' ? 'out' : 'in', d: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}` }
      })

      return { nodes: [...positioned.values()], edges, height }
    },
    hotPaths() {
      if (!this.hovered) return null
      return this.graph.memberOf.get(this.hovered) || new Set()
    }
  },
  methods: {
    isHot(id) {
      if (!this.hotPaths) return false
      if (id === this.hovered) return true
      const own = this.graph.memberOf.get(id)
      return !!own && [...own].some(p => this.hotPaths.has(p))
    },
    isDim(id) {
      return !!this.hotPaths && !this.isHot(id)
    },
    truncate(text, max) {
      const s = String(text || '')
      return s.length > max ? `${s.slice(0, max - 1)}…` : s
    },
    openNode(node) {
      if (node.raw) return
      const target = { datapull: '/datapulls', enrichment: '/data-enrichments', output: '/outputs' }[node.column]
      if (target) this.$router.push(target)
    }
  }
}
</script>

<style scoped>
.flow-svg {
  width: 100%;
  height: auto;
  display: block;
  font-family: inherit;
}

.col-header {
  font-size: 13px;
  font-weight: 700;
  fill: #14213d;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.flow-edge {
  fill: none;
  stroke-width: 1.6;
  opacity: 0.55;
  transition: opacity 0.15s, stroke-width 0.15s;
}

.edge-in { stroke: #fca311; }
.edge-out { stroke: #2a9d8f; }

.flow-edge.is-hot { opacity: 1; stroke-width: 2.6; }
.flow-edge.is-dim { opacity: 0.08; }

.flow-node {
  cursor: pointer;
  transition: opacity 0.15s;
}

.flow-node rect:first-of-type {
  fill: #ffffff;
  stroke: #d5d9e2;
  stroke-width: 1;
}

.flow-node.is-hot rect:first-of-type { stroke: #14213d; stroke-width: 1.6; }
.flow-node.is-dim { opacity: 0.25; }

.node-datapull .node-accent { fill: #14213d; }
.node-enrichment .node-accent { fill: #fca311; }
.node-output .node-accent { fill: #2a9d8f; }

.flow-node.is-disabled .node-accent { fill: #adb5bd; }
.flow-node.is-disabled rect:first-of-type { stroke-dasharray: 4 3; fill: #f5f6f8; }
.flow-node.is-missing rect:first-of-type { stroke: #e76f51; }

.node-label {
  font-size: 13px;
  font-weight: 600;
  fill: #1f2937;
}

.flow-node.is-disabled .node-label { fill: #6c757d; }

.node-meta {
  font-size: 11px;
  fill: #6c757d;
}

.flow-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem 1.1rem;
  margin-top: 0.75rem;
  font-size: 0.82rem;
}

.swatch {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  margin-right: 0.35rem;
  vertical-align: -1px;
}

.swatch-datapull { background: #14213d; }
.swatch-enrichment { background: #fca311; }
.swatch-output { background: #2a9d8f; }
.swatch-disabled { background: #adb5bd; }
</style>
