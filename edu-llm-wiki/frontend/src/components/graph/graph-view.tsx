import { useEffect, useState, useMemo, useCallback, useRef } from "react"
import { createPortal } from "react-dom"
import Graph from "graphology"
import { SigmaContainer, useLoadGraph, useRegisterEvents, useSetSettings, useSigma } from "@react-sigma/core"
import "@react-sigma/core/lib/style.css"
import forceAtlas2 from "graphology-layout-forceatlas2"
import { Network, RefreshCw, ZoomIn, ZoomOut, Maximize, Tag, Layers, Filter, X, Search, RotateCcw } from "lucide-react"
import { api } from "@/lib/api"
import type { GraphData } from "@/types/wiki"

const TYPE_COLORS: Record<string, string> = {
  concept: "#3b82f6",
  formula: "#8b5cf6",
  principle: "#f59e0b",
  exercise: "#10b981",
  source: "#6b7280",
  synthesis: "#ec4899",
}

const COMMUNITY_COLORS = [
  "#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6",
  "#ec4899", "#06b6d4", "#84cc16", "#f97316", "#6366f1",
  "#14b8a6", "#a855f7",
]

type ColorMode = "type" | "community"
type HoverState = { node: string; neighbors: Set<string>; hoveredEdge: string | null } | null

function nodeColor(type: string): string {
  return TYPE_COLORS[type] || "#94a3b8"
}

function mixColor(color: string, mix: string, ratio: number): string {
  const hex = (c: string, i: number) => parseInt(c.slice(i * 2 + 1, i * 2 + 3), 16)
  const r = Math.round(hex(color, 0) + (hex(mix, 0) - hex(color, 0)) * ratio)
  const g = Math.round(hex(color, 1) + (hex(mix, 1) - hex(color, 1)) * ratio)
  const b = Math.round(hex(color, 2) + (hex(mix, 2) - hex(color, 2)) * ratio)
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`
}

function layoutIterations(count: number): number {
  if (count > 500) return 30
  if (count > 200) return 60
  return 100
}

// ─── Inner Components ─────────────────────────────────────────────

function GraphLoader({
  data, colorMode, nodeScale, spacing,
}: {
  data: GraphData
  colorMode: ColorMode
  nodeScale: number
  spacing: number
}) {
  const loadGraph = useLoadGraph()
  const sigma = useSigma()
  const loadedRef = useRef("")

  useEffect(() => {
    const key = `${data.nodes.length}:${data.edges.length}:${colorMode}:${nodeScale}:${spacing}`
    if (key === loadedRef.current) return
    loadedRef.current = key

    const graph = new Graph()
    const maxSize = Math.max(...data.nodes.map((n) => n.size), 1)
    const cx = 0
    const cy = 0
    const radius = 5

    for (let i = 0; i < data.nodes.length; i++) {
      const node = data.nodes[i]
      const angle = (2 * Math.PI * i) / data.nodes.length
      const size = 4 + (Math.sqrt(node.size) / Math.sqrt(maxSize)) * 16
      const color = colorMode === "community" && node.community >= 0
        ? COMMUNITY_COLORS[node.community % COMMUNITY_COLORS.length]
        : nodeColor(node.node_type)

      graph.addNode(node.id, {
        x: cx + radius * Math.cos(angle),
        y: cy + radius * Math.sin(angle),
        size: size * nodeScale,
        color,
        label: node.label,
        nodeType: node.node_type,
        community: node.community,
      })
    }

    const edgeWeights = data.edges.map((e) => e.weight)
    const minW = Math.min(...edgeWeights)
    const maxW = Math.max(...edgeWeights)
    const weightRange = maxW - minW || 1

    for (const edge of data.edges) {
      if (graph.hasNode(edge.source) && graph.hasNode(edge.target)) {
        const key = `${edge.source}->${edge.target}`
        if (!graph.hasEdge(key) && !graph.hasEdge(`${edge.target}->${edge.source}`)) {
          const t = (edge.weight - minW) / weightRange
          const opacity = 0.12 + t * 0.78
          graph.addEdgeWithKey(key, edge.source, edge.target, {
            size: 0.3 + t * 3.7,
            color: `rgba(71,85,105,${opacity})`,
            weight: edge.weight,
            label: edge.weight.toFixed(1),
          })
        }
      }
    }

    // ForceAtlas2 layout
    if (data.nodes.length > 1) {
      const settings = forceAtlas2.inferSettings(graph)
      forceAtlas2.assign(graph, {
        iterations: layoutIterations(data.nodes.length),
        settings: {
          ...settings,
          gravity: 1,
          scalingRatio: spacing * 2,
          strongGravityMode: true,
          barnesHutOptimize: data.nodes.length > 50,
        },
      })
    }

    loadGraph(graph)
    sigma.refresh()
  }, [data, colorMode, nodeScale, spacing, loadGraph, sigma])

  return null
}

function GraphSettings({
  hoverState, highlightedNodes, nodeCount,
}: {
  hoverState: HoverState
  highlightedNodes: Set<string>
  nodeCount: number
}) {
  const setSettings = useSetSettings()
  const sigma = useSigma()

  useEffect(() => {
    setSettings({
      hideEdgesOnMove: true,
      hideLabelsOnMove: true,
      labelDensity: nodeCount > 200 ? 0.2 : 0.4,
      labelRenderedSizeThreshold: nodeCount > 200 ? 14 : 6,
      nodeReducer: (_node, attrs) => {
        const result = { ...attrs }
        const hasHover = !!hoverState
        const hasHighlight = highlightedNodes.size > 0
        const isHoverNode = hoverState?.node === _node
        const isHoverNeighbor = hoverState?.neighbors.has(_node) ?? false
        const isHighlighted = highlightedNodes.has(_node)

        if (isHighlighted || isHoverNode) {
          result.size = (attrs.size ?? 8) * 1.4
          result.zIndex = 10
          result.forceLabel = true
        }
        if ((hasHover && !isHoverNode && !isHoverNeighbor) || (hasHighlight && !isHighlighted)) {
          result.color = mixColor(attrs.color ?? "#94a3b8", "#e2e8f0", 0.7)
          result.label = ""
          result.size = (attrs.size ?? 8) * 0.5
        }
        return result
      },
      edgeReducer: (_edge, attrs) => {
        const result = { ...attrs }
        const hasHover = !!hoverState
        const hasHighlight = highlightedNodes.size > 0
        const isEdgeHover = hasHover && hoverState?.hoveredEdge !== null
        const isNodeHover = hasHover && !isEdgeHover
        const hoverEdge = isNodeHover && _edge.includes(hoverState?.node ?? "")
        const highlightedEdge = hasHighlight && highlightedNodes.has(attrs.source) && highlightedNodes.has(attrs.target)
        const isHoveredEdge = isEdgeHover && hoverState?.hoveredEdge === _edge

        // Show label for highlighted/neighbor edges, hide for faded ones.
        result.label = (hoverEdge || highlightedEdge) ? (attrs.label ?? "") : ""

        if (isEdgeHover) {
          if (isHoveredEdge) {
            result.color = "#1e293b"
            result.size = Math.max(2.5, (attrs.size ?? 1) * 1.8)
            result.zIndex = 10
          } else {
            result.color = "#f1f5f9"
            result.size = 0.3
            result.zIndex = 0
          }
        } else {
          if ((hasHover && !hoverEdge) || (hasHighlight && !highlightedEdge)) {
            result.color = "#f1f5f9"
            result.size = 0.3
            result.zIndex = 0
          }
          if (hoverEdge || highlightedEdge) {
            result.color = "#334155"
            result.size = Math.max(2, (attrs.size ?? 1) * 1.5)
            result.zIndex = 5
          }
        }
        return result
      },
    })
    sigma.refresh()
  }, [setSettings, sigma, hoverState, highlightedNodes, nodeCount])

  return null
}

function EventHandler({
  onNodeClick, onHoverChange,
}: {
  onNodeClick: (nodeId: string) => void
  onHoverChange: (state: HoverState) => void
}) {
  const registerEvents = useRegisterEvents()
  const sigma = useSigma()
  const dragRef = useRef<string | null>(null)

  useEffect(() => {
    registerEvents({
      clickNode: ({ node }) => onNodeClick(node),

      // Node hover — highlight neighbors
      enterNode: ({ node }) => {
        sigma.getContainer().style.cursor = "pointer"
        onHoverChange({ node, neighbors: new Set(sigma.getGraph().neighbors(node)), hoveredEdge: null })
      },
      leaveNode: () => {
        sigma.getContainer().style.cursor = "default"
        onHoverChange(null)
      },

      // Edge hover — show pointer cursor and activate label
      enterEdge: (e) => {
        sigma.getContainer().style.cursor = "pointer"
        onHoverChange({ node: "", neighbors: new Set(), hoveredEdge: e.edge })
      },
      leaveEdge: () => {
        sigma.getContainer().style.cursor = "default"
        onHoverChange(null)
      },

      // Node dragging — prevent sigma default to stop camera panning
      downNode: (e) => {
        e.preventSigmaDefault()
        dragRef.current = e.node
        sigma.getContainer().style.cursor = "grabbing"
      },
      mousemove: (e) => {
        if (!dragRef.current) return
        e.preventSigmaDefault()
        const pos = sigma.viewportToGraph({ x: e.x, y: e.y })
        sigma.getGraph().setNodeAttribute(dragRef.current, "x", pos.x)
        sigma.getGraph().setNodeAttribute(dragRef.current, "y", pos.y)
        sigma.refresh()
      },
      mouseup: (e) => {
        if (dragRef.current) {
          e.preventSigmaDefault()
          dragRef.current = null
          sigma.getContainer().style.cursor = "default"
        }
      },
    })
  }, [registerEvents, sigma, onNodeClick, onHoverChange])

  return null
}

function EdgeLabelOverlay({ hoverState }: { hoverState: HoverState }) {
  const sigma = useSigma()
  const [, forceTick] = useState(0)
  const containerRef = useRef<HTMLDivElement>(null)

  // Re-render on each frame while hovering, to track camera movement
  useEffect(() => {
    if (!hoverState) return
    let raf: number
    const tick = () => {
      forceTick((n) => n + 1)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [hoverState])

  if (!hoverState) return null

  const container = sigma.getContainer()
  const rect = container.getBoundingClientRect()
  const labels: { key: string; x: number; y: number; text: string }[] = []
  const graph = sigma.getGraph()

  if (hoverState.node) {
    // Node hover: show labels for incident edges
    graph.forEachEdge(hoverState.node, (edge) => {
      const ext = graph.extremities(edge)
      if (!ext) return
      const sx = graph.getNodeAttribute(ext[0], "x") as number
      const sy = graph.getNodeAttribute(ext[0], "y") as number
      const tx = graph.getNodeAttribute(ext[1], "x") as number
      const ty = graph.getNodeAttribute(ext[1], "y") as number
      const weight = graph.getEdgeAttribute(edge, "weight") as number
      const vp = sigma.framedGraphToViewport({ x: (sx + tx) / 2, y: (sy + ty) / 2 })
      labels.push({
        key: edge,
        x: rect.left + vp.x,
        y: rect.top + vp.y - 8,
        text: weight.toFixed(1),
      })
    })
  } else if (hoverState.hoveredEdge) {
    const edge = hoverState.hoveredEdge
    const ext = graph.extremities(edge)
    if (ext) {
      const sx = graph.getNodeAttribute(ext[0], "x") as number
      const sy = graph.getNodeAttribute(ext[0], "y") as number
      const tx = graph.getNodeAttribute(ext[1], "x") as number
      const ty = graph.getNodeAttribute(ext[1], "y") as number
      const weight = graph.getEdgeAttribute(edge, "weight") as number
      const vp = sigma.framedGraphToViewport({ x: (sx + tx) / 2, y: (sy + ty) / 2 })
      labels.push({
        key: edge,
        x: rect.left + vp.x,
        y: rect.top + vp.y - 8,
        text: weight.toFixed(1),
      })
    }
  }

  return createPortal(
    <div ref={containerRef} className="fixed inset-0 pointer-events-none" style={{ zIndex: 99999 }}>
      {labels.map((l) => (
        <div
          key={l.key}
          className="absolute text-xs font-semibold"
          style={{
            left: l.x,
            top: l.y,
            transform: "translate(-50%, -50%)",
            color: "#0f172a",
            textShadow: "0 0 4px rgba(255,255,255,0.95), 0 0 8px rgba(255,255,255,0.8), 0 0 2px #fff",
            whiteSpace: "nowrap",
            pointerEvents: "none",
          }}
        >
          {l.text}
        </div>
      ))}
    </div>,
    document.body,
  )
}

function ZoomControls() {
  const sigma = useSigma()

  return (
    <div className="absolute top-3 right-3 flex flex-col gap-1">
      <button
        className="h-7 w-7 flex items-center justify-center rounded border bg-[var(--background)]/80 backdrop-blur-sm hover:bg-[var(--accent)]"
        onClick={() => sigma.getCamera().animatedZoom({ duration: 200 })}
      >
        <ZoomIn className="h-3.5 w-3.5" />
      </button>
      <button
        className="h-7 w-7 flex items-center justify-center rounded border bg-[var(--background)]/80 backdrop-blur-sm hover:bg-[var(--accent)]"
        onClick={() => sigma.getCamera().animatedUnzoom({ duration: 200 })}
      >
        <ZoomOut className="h-3.5 w-3.5" />
      </button>
      <button
        className="h-7 w-7 flex items-center justify-center rounded border bg-[var(--background)]/80 backdrop-blur-sm hover:bg-[var(--accent)]"
        onClick={() => sigma.getCamera().animatedReset({ duration: 300 })}
      >
        <Maximize className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}

// ─── Main Component ───────────────────────────────────────────────

export function GraphView() {
  const [data, setData] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const [colorMode, setColorMode] = useState<ColorMode>("type")
  const [hoverState, setHoverState] = useState<HoverState>(null)
  const [highlightedNodes, setHighlightedNodes] = useState<Set<string>>(new Set())
  const [showFilters, setShowFilters] = useState(false)
  const [showInsights, setShowInsights] = useState(false)
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set())
  const [nodeScale, setNodeScale] = useState(1)
  const [spacing, setSpacing] = useState(1)
  const [graphSearch, setGraphSearch] = useState("")
  const [searchOpen, setSearchOpen] = useState(false)
  const searchInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.getGraph()
      .then(setData)
      .catch((e) => setError(e?.message || "Failed to load graph"))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (searchOpen) searchInputRef.current?.focus()
  }, [searchOpen])

  // Filter by hidden types
  const filteredNodes = useMemo(() => {
    if (!data) return []
    if (hiddenTypes.size === 0) return data.nodes
    return data.nodes.filter((n) => !hiddenTypes.has(n.node_type))
  }, [data, hiddenTypes])

  const filteredNodeIds = useMemo(() => new Set(filteredNodes.map((n) => n.id)), [filteredNodes])

  const filteredEdges = useMemo(() => {
    if (!data) return []
    return data.edges.filter((e) => filteredNodeIds.has(e.source) && filteredNodeIds.has(e.target))
  }, [data, filteredNodeIds])

  // Graph search
  const searchResults = useMemo(() => {
    const q = graphSearch.trim().toLowerCase()
    if (!q || !data) return { nodes: filteredNodes, edges: filteredEdges, matched: new Set<string>() }
    const matched = new Set<string>()
    for (const n of filteredNodes) {
      if (n.label.toLowerCase().includes(q) || n.node_type.toLowerCase().includes(q)) {
        matched.add(n.id)
      }
    }
    // Also include neighbors of matched nodes
    const neighborSet = new Set(matched)
    for (const e of filteredEdges) {
      if (matched.has(e.source)) neighborSet.add(e.target)
      if (matched.has(e.target)) neighborSet.add(e.source)
    }
    return {
      nodes: filteredNodes.filter((n) => neighborSet.has(n.id)),
      edges: filteredEdges.filter((e) => neighborSet.has(e.source) && neighborSet.has(e.target)),
      matched,
    }
  }, [filteredNodes, filteredEdges, graphSearch, data])

  const visibleData: GraphData | null = useMemo(() => {
    if (!data) return null
    return {
      ...data,
      nodes: searchResults.nodes,
      edges: searchResults.edges,
    }
  }, [data, searchResults])

  const handleNodeClick = useCallback((nodeId: string) => {
    setSelectedNode((prev) => (prev === nodeId ? null : nodeId))
  }, [])

  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    if (!data) return counts
    for (const n of data.nodes) {
      counts[n.node_type] = (counts[n.node_type] ?? 0) + 1
    }
    return counts
  }, [data])

  const totalHidden = data ? data.nodes.length - filteredNodes.length : 0
  const filtersActive = hiddenTypes.size > 0 || nodeScale !== 1 || spacing !== 1
  const searchActive = graphSearch.trim().length > 0
  const hasInsights = data && data.insights.length > 0

  if (loading) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-[var(--muted-foreground)]">
        <RefreshCw className="h-8 w-8 animate-spin opacity-50" />
        <p className="text-sm">Building graph...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-[var(--muted-foreground)]">
        <Network className="h-10 w-10 opacity-30" />
        <p className="text-sm text-red-500">{error}</p>
      </div>
    )
  }

  if (!data || data.nodes.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--muted-foreground)]">
        <div className="text-center">
          <p className="text-lg mb-2">No graph data yet</p>
          <p>Import documents and run ingest to build the knowledge graph.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header toolbar */}
      <div className="shrink-0 flex items-center justify-between border-b px-3 py-1.5">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Network className="h-4 w-4 text-[var(--muted-foreground)]" />
            <span className="text-sm font-medium">Knowledge Graph</span>
          </div>
          <div className="flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]">
            <span className="rounded bg-[var(--muted)] px-1.5 py-0.5">
              {searchResults.nodes.length}/{data.nodes.length} nodes
            </span>
            <span className="rounded bg-[var(--muted)] px-1.5 py-0.5">
              {searchResults.edges.length}/{data.edges.length} edges
            </span>
            {totalHidden > 0 && (
              <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-amber-600">
                {totalHidden} hidden
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1">
          {/* Search */}
          {searchOpen || searchActive ? (
            <div className="relative mr-1 w-44">
              <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted-foreground)]" />
              <input
                ref={searchInputRef}
                value={graphSearch}
                onChange={(e) => setGraphSearch(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Escape") { setGraphSearch(""); setSearchOpen(false) } }}
                className="h-7 w-full rounded-md border bg-[var(--background)] pl-7 pr-7 text-xs outline-none focus:border-[var(--primary)]"
                placeholder="Search nodes..."
              />
              <button
                className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                onClick={() => { setGraphSearch(""); setSearchOpen(false) }}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : (
            <button onClick={() => setSearchOpen(true)} className="h-7 px-2 text-xs rounded hover:bg-[var(--accent)] text-[var(--muted-foreground)] flex items-center gap-1">
              <Search className="h-3.5 w-3.5" />
            </button>
          )}

          {/* Filter toggle */}
          <button
            onClick={() => setShowFilters((v) => !v)}
            className={`h-7 px-2 text-xs rounded flex items-center gap-1 ${showFilters ? "bg-[var(--muted)]" : "hover:bg-[var(--accent)] text-[var(--muted-foreground)]"}`}
          >
            <Filter className="h-3 w-3" />
          </button>

          {/* Fillters reset */}
          {filtersActive && (
            <button
              onClick={() => { setHiddenTypes(new Set()); setNodeScale(1); setSpacing(1) }}
              className="h-7 px-2 text-xs rounded hover:bg-[var(--accent)] text-[var(--muted-foreground)] flex items-center gap-1"
            >
              <RotateCcw className="h-3 w-3" />
            </button>
          )}

          {/* Color mode */}
          <button
            onClick={() => setColorMode("type")}
            className={`h-7 px-2 text-xs rounded flex items-center gap-1 ${colorMode === "type" ? "bg-[var(--muted)]" : "hover:bg-[var(--accent)] text-[var(--muted-foreground)]"}`}
          >
            <Tag className="h-3 w-3" />
          </button>
          <button
            onClick={() => setColorMode("community")}
            className={`h-7 px-2 text-xs rounded flex items-center gap-1 ${colorMode === "community" ? "bg-[var(--muted)]" : "hover:bg-[var(--accent)] text-[var(--muted-foreground)]"}`}
          >
            <Layers className="h-3 w-3" />
          </button>

          {/* Insights */}
          {hasInsights && (
            <button
              onClick={() => setShowInsights((v) => !v)}
              className={`h-7 px-2 text-xs rounded flex items-center gap-1 ${showInsights ? "bg-[var(--muted)]" : "hover:bg-[var(--accent)] text-[var(--muted-foreground)]"}`}
            >
              {data.insights.length}
            </button>
          )}
        </div>
      </div>

      {/* Canvas area */}
      <div className="flex-1 min-h-0 flex">
        <div className="relative flex-1 min-w-0 bg-slate-50 dark:bg-slate-950">
          {!visibleData || visibleData.nodes.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-[var(--muted-foreground)]">
              <Search className="h-8 w-8 opacity-40" />
              <p className="text-sm">{searchActive ? "No matching nodes" : "No visible nodes"}</p>
            </div>
          ) : (
            <SigmaContainer
              style={{ width: "100%", height: "100%", background: "transparent" }}
              settings={{
                renderEdgeLabels: true,
                enableEdgeEvents: true,
                hideEdgesOnMove: true,
                zIndex: true,
                defaultEdgeColor: "#cbd5e1",
                defaultNodeColor: "#94a3b8",
                labelSize: 11,
                labelColor: { color: "#334155" },
                edgeLabelSize: 14,
                edgeLabelColor: { color: "#0f172a" },
                labelDensity: 0.1,
                labelRenderedSizeThreshold: 2,
                hideLabelsOnMove: false,
                stagePadding: 30,
              }}
            >
              <GraphLoader data={visibleData} colorMode={colorMode} nodeScale={nodeScale} spacing={spacing} />
              <EventHandler onNodeClick={handleNodeClick} onHoverChange={setHoverState} />
              <GraphSettings
                hoverState={hoverState}
                highlightedNodes={searchActive ? searchResults.matched : highlightedNodes}
                nodeCount={visibleData.nodes.length}
              />
              <EdgeLabelOverlay hoverState={hoverState} />
              <ZoomControls />
            </SigmaContainer>
          )}

          {/* Filter panel */}
          {showFilters && (
            <div className="absolute top-3 left-3 w-56 rounded-lg border bg-[var(--background)]/95 p-2 text-xs shadow-lg backdrop-blur-sm space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1 font-semibold">
                  <Filter className="h-3 w-3" />
                  Filters
                </div>
              </div>

              {/* Node scale slider */}
              <label className="block space-y-1">
                <div className="flex justify-between">
                  <span className="text-[var(--muted-foreground)]">Node size</span>
                  <span>{Math.round(nodeScale * 100)}%</span>
                </div>
                <input
                  type="range" min={0.5} max={1.5} step={0.05}
                  value={nodeScale}
                  onChange={(e) => setNodeScale(Number(e.target.value))}
                  className="w-full h-1"
                />
              </label>

              {/* Spacing slider */}
              <label className="block space-y-1">
                <div className="flex justify-between">
                  <span className="text-[var(--muted-foreground)]">Spacing</span>
                  <span>{Math.round(spacing * 100)}%</span>
                </div>
                <input
                  type="range" min={0.6} max={2} step={0.05}
                  value={spacing}
                  onChange={(e) => setSpacing(Number(e.target.value))}
                  className="w-full h-1"
                />
              </label>

              {/* Type toggles */}
              <div className="space-y-1">
                <div className="font-medium text-[var(--muted-foreground)]">Node types</div>
                {Object.entries(typeCounts).map(([type, count]) => (
                  <label key={type} className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={!hiddenTypes.has(type)}
                      onChange={(e) => {
                        setHiddenTypes((prev) => {
                          const next = new Set(prev)
                          e.target.checked ? next.delete(type) : next.add(type)
                          return next
                        })
                      }}
                    />
                    <span className="w-2 h-2 rounded-full" style={{ background: nodeColor(type) }} />
                    <span className="truncate">{type}</span>
                    <span className="text-[var(--muted-foreground)] ml-auto">{count}</span>
                  </label>
                ))}
              </div>
            </div>
          )}

          {/* Legend */}
          <div className="absolute bottom-3 left-3 rounded-lg border bg-[var(--background)]/90 backdrop-blur-sm px-2.5 py-1.5 text-xs shadow-sm max-w-[220px]">
            <div className="flex items-center gap-1 mb-1">
              <span className="font-semibold text-xs">
                {colorMode === "type" ? "Node Types" : "Communities"}
              </span>
            </div>
            {colorMode === "type"
              ? Object.entries(typeCounts).slice(0, 8).map(([type, count]) => {
                  const hidden = hiddenTypes.has(type)
                  return (
                    <div
                      key={type}
                      className={`flex items-center gap-1.5 py-0.5 rounded px-0.5 hover:bg-[var(--accent)]/50 cursor-pointer ${hidden ? "opacity-30" : ""}`}
                      onClick={() => setHiddenTypes((prev) => {
                        const next = new Set(prev)
                        hidden ? next.delete(type) : next.add(type)
                        return next
                      })}
                    >
                      <span className="w-2 h-2 rounded-full shrink-0" style={{ background: nodeColor(type) }} />
                      <span className="text-[var(--muted-foreground)] truncate">{type}</span>
                      <span className="text-[var(--muted-foreground)]/60 ml-auto">{count}</span>
                    </div>
                  )
                })
              : communitiesSlice(data).map((c, i) => (
                  <div key={c.label} className="flex items-center gap-1.5 py-0.5 rounded px-0.5">
                    <span className="w-2 h-2 rounded-full shrink-0" style={{ background: COMMUNITY_COLORS[i % COMMUNITY_COLORS.length] }} />
                    <span className="text-[var(--muted-foreground)] truncate">{c.label}</span>
                    <span className="text-[var(--muted-foreground)]/60 ml-auto">{c.member_count}</span>
                  </div>
                ))
            }
          </div>
        </div>

        {/* Insights panel */}
        {showInsights && hasInsights && (
          <div className="w-72 shrink-0 border-l bg-[var(--background)] overflow-y-auto">
            <div className="flex items-center justify-between px-3 py-2 border-b">
              <span className="text-sm font-medium">Insights</span>
              <button onClick={() => setShowInsights(false)} className="p-0.5 rounded hover:bg-[var(--muted)]">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="p-3 space-y-2">
              {data.insights.map((insight, i) => (
                <div
                  key={i}
                  className="rounded-lg border p-3 text-xs cursor-pointer hover:bg-[var(--muted)]/50 transition-colors"
                  onClick={() => {
                    const ids = new Set(insight.node_ids)
                    const isActive = highlightedNodes.size === ids.size && [...ids].every((id) => highlightedNodes.has(id))
                    setHighlightedNodes(isActive ? new Set() : ids)
                  }}
                >
                  <span className={`font-medium ${
                    insight.insight_type === "knowledge_gap" ? "text-orange-500" :
                    insight.insight_type === "bridge" ? "text-blue-500" :
                    "text-purple-500"
                  }`}>
                    {insight.title}
                  </span>
                  <p className="text-[var(--muted-foreground)] mt-1">{insight.description}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function communitiesSlice(data: GraphData): { label: string; member_count: number }[] {
  return data.communities.slice(0, 8).map((c, i) => ({
    label: c.top_node?.slice(0, 15) || `Cluster ${c.id}`,
    member_count: c.member_count,
  }))
}
