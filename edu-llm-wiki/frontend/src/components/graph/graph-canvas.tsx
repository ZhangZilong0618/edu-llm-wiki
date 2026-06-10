// Sigma.js wrapper: builds a graphology Graph from GraphData, runs the
// ForceAtlas2 layout once, and forwards interaction events to the parent
// via callbacks. Settings reducers (nodeReducer / edgeReducer) implement
// hover and selection highlighting.

import { useEffect, useMemo, useRef } from "react"
import Graph from "graphology"
import {
  SigmaContainer,
  useLoadGraph,
  useRegisterEvents,
  useSetSettings,
  useSigma,
} from "@react-sigma/core"
import "@react-sigma/core/lib/style.css"
import forceAtlas2 from "graphology-layout-forceatlas2"

import { DEFAULT_HIDDEN_TYPES, type ColorMode } from "./constants"
import { layoutIterations, mixColor, nodeColor, normalizePositions, packComponents, readableLabel } from "./utils"
import type { GraphData, GraphNode } from "@/types/wiki"

export type GraphSelection = {
  node: GraphNode
  degree: number
} | null

export type GraphHoverState = {
  node: string
  neighbors: Set<string>
} | null

export interface GraphCanvasProps {
  data: GraphData
  selected: GraphSelection
  hover: GraphHoverState
  searchQuery: string
  hiddenTypes: Set<string>
  colorMode: ColorMode
  communityColors: string[]
  nodeScale: number
  spacing: number
  showWeakLinks: boolean
  onSelect: (nodeId: string) => void
  onHover: (state: GraphHoverState) => void
}

export function GraphCanvas(props: GraphCanvasProps) {
  return (
    <SigmaContainer
      style={{ width: "100%", height: "100%" }}
      settings={{
        renderEdgeLabels: false,
        labelDensity: 0.7,
        labelGridCellSize: 60,
        labelRenderedSizeThreshold: 8,
      }}
    >
      <GraphCanvasInner {...props} />
    </SigmaContainer>
  )
}

function GraphCanvasInner({
  data,
  selected,
  hover,
  searchQuery,
  hiddenTypes,
  colorMode,
  communityColors,
  nodeScale,
  spacing,
  showWeakLinks,
  onSelect,
  onHover,
}: GraphCanvasProps) {
  const loadGraph = useLoadGraph()
  const registerEvents = useRegisterEvents()
  const setSettings = useSetSettings()
  const sigma = useSigma()
  const loadedRef = useRef<string>("")

  const signature = useMemo(() => {
    const nIds = data.nodes.map((n) => n.id).join("|")
    const eIds = data.edges
      .map((e) => `${e.source}>${e.target}:${e.edge_type}:${e.weight}`)
      .join("|")
    return `${nIds}::${eIds}::${colorMode}::${nodeScale}::${spacing}::${Array.from(hiddenTypes).sort().join(",")}::${showWeakLinks}`
  }, [data, colorMode, nodeScale, spacing, hiddenTypes, showWeakLinks])

  useEffect(() => {
    if (loadedRef.current === signature) return
    loadedRef.current = signature

    const g = new Graph({ multi: true, type: "directed" })

    // Seed nodes on a circle; FA2 will spread them out.
    const total = data.nodes.length || 1
    const radius = Math.max(80, Math.sqrt(total) * 30)
    data.nodes.forEach((n, i) => {
      const angle = (i / total) * Math.PI * 2
      g.addNode(n.id, {
        x: Math.cos(angle) * radius + radius,
        y: Math.sin(angle) * radius + radius,
        size: n.size * nodeScale,
        color: nodeColor(n.node_type),
        label: readableLabel(n.label),
        fullLabel: n.label,
        nodeType: n.node_type,
        community: n.community,
      })
    })

    data.edges.forEach((e) => {
      if (!g.hasNode(e.source) || !g.hasNode(e.target)) return
      if (!g.hasEdge(e.source, e.target)) {
        g.addDirectedEdgeWithKey(`${e.source}>${e.target}`, e.source, e.target, {
          size: Math.min(5, 1 + e.weight / 4),
          color: "rgba(100,116,139,0.55)",
          weight: e.weight,
          edgeType: e.edge_type,
        })
      }
    })

    if (data.nodes.length > 0) {
      forceAtlas2.assign(g, {
        iterations: layoutIterations(data.nodes.length),
        settings: { gravity: 1, scalingRatio: 10, slowDown: 5 },
      })
      normalizePositions(g)
      packComponents(g, spacing)
    }

    loadGraph(g)
    requestAnimationFrame(() => sigma.refresh())
  }, [signature, data, nodeScale, spacing, loadGraph, sigma])

  // Filter by type / showWeakLinks
  useEffect(() => {
    const isStrongEdge = (e: { edge_type: string; weight: number }) =>
      e.edge_type === "direct" || e.edge_type === "prerequisite" || e.weight >= 8
    setSettings({
      nodeReducer: (node, attrs) => {
        const type = (attrs as any).nodeType as string
        if (hiddenTypes.has(type)) return { ...attrs, hidden: true }
        if (selected && selected.node.id === node) {
          return { ...attrs, size: (attrs.size as number) * 1.3, zIndex: 10 }
        }
        if (hover && hover.node === node) {
          return { ...attrs, size: (attrs.size as number) * 1.4, zIndex: 10 }
        }
        if (hover && hover.neighbors.has(String(node))) {
          return { ...attrs, zIndex: 5 }
        }
        if (hover) {
          return {
            ...attrs,
            color: mixColor(attrs.color as string, "#e2e8f0", 0.65),
            size: (attrs.size as number) * 0.55,
            zIndex: 1,
          }
        }
        if (searchQuery.trim()) {
          const q = searchQuery.trim().toLowerCase()
          const matches =
            (attrs.label as string).toLowerCase().includes(q) ||
            ((attrs as any).nodeType as string).toLowerCase().includes(q)
          const neighborSet: Set<string> | undefined = hover ? (hover as any).neighbors : undefined
          if (!matches && !(neighborSet && neighborSet.has(String(node)))) {
            return {
              ...attrs,
              color: mixColor(attrs.color as string, "#e2e8f0", 0.45),
              size: (attrs.size as number) * 0.7,
              zIndex: 0,
            }
          }
          return { ...attrs, size: (attrs.size as number) * 1.2, zIndex: 5 }
        }
        if (colorMode === "community") {
          const community = (attrs as any).community as number
          if (community >= 0) {
            return { ...attrs, color: communityColors[community % communityColors.length] }
          }
        }
        return attrs
      },
      edgeReducer: (edge, attrs) => {
        const e = data.edges.find(
          (x) => x.source === edge && x.target === attrs.source,
        )
        void e
        if (!showWeakLinks) {
          const ev = (attrs as any).edgeType as string
          const w = (attrs as any).weight as number
          if (!isStrongEdge({ edge_type: ev, weight: w })) {
            return { ...attrs, hidden: true }
          }
        }
        return attrs
      },
    })
  }, [setSettings, hiddenTypes, selected, hover, searchQuery, colorMode, communityColors, data.edges, showWeakLinks])

  useEffect(() => {
    registerEvents({
      clickNode: ({ node }) => onSelect(node),
      enterNode: ({ node }) => {
        const graph = sigma.getGraph() as unknown as { neighbors: (n: string) => Iterable<string> }
        const neighbors = new Set<string>(Array.from(graph.neighbors(node)))
        onHover({ node, neighbors })
      },
      leaveNode: () => onHover(null),
    })
  }, [registerEvents, sigma, onSelect, onHover])

  return null
}