import { useEffect, useRef, useState, useMemo } from "react"
import { api } from "@/lib/api"
import type { GraphData } from "@/types/wiki"
import { Loader2 } from "lucide-react"

export function GraphView() {
  const [data, setData] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedNode, setSelectedNode] = useState<string | null>(null)

  useEffect(() => {
    api.getGraph().then((d) => {
      setData(d)
      setLoading(false)
    }).catch(console.error)
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 size={24} className="animate-spin text-[var(--muted-foreground)]" />
      </div>
    )
  }

  if (!data || data.nodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-[var(--muted-foreground)]">
        <div className="text-center">
          <p className="text-lg mb-2">No graph data yet</p>
          <p>Import documents and run ingest to build the knowledge graph.</p>
        </div>
      </div>
    )
  }

  const typeColors: Record<string, string> = {
    concept: "#3b82f6", formula: "#8b5cf6", principle: "#f59e0b",
    exercise: "#10b981", source: "#6b7280", synthesis: "#ec4899",
  }

  const communityColors = [
    "#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6",
    "#ec4899", "#06b6d4", "#84cc16", "#f97316", "#6366f1",
    "#14b8a6", "#a855f7",
  ]

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="shrink-0 flex items-center justify-between px-3 py-2 border-b">
        <div className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
          <span>{data.nodes.length} nodes</span>
          <span>·</span>
          <span>{data.edges.length} edges</span>
          <span>·</span>
          <span>{data.communities.length} communities</span>
        </div>
      </div>

      {/* Graph canvas */}
      <div className="flex-1 overflow-hidden relative bg-[var(--background)]">
        <SvgGraph
          key={selectedNode ?? "all"}
          data={data}
          typeColors={typeColors}
          communityColors={communityColors}
          selectedNode={selectedNode}
          onSelectNode={setSelectedNode}
        />
      </div>

      {/* Legend */}
      <div className="shrink-0 flex flex-wrap gap-3 px-3 py-2 border-t text-[10px]">
        {Object.entries(typeColors).map(([type, color]) => {
          const count = data.nodes.filter((n) => n.node_type === type).length
          if (count === 0) return null
          return (
            <div key={type} className="flex items-center gap-1">
              <div className="w-2.5 h-2.5 rounded-full" style={{ background: color }} />
              <span className="text-[var(--muted-foreground)]">{type} ({count})</span>
            </div>
          )
        })}
      </div>

      {/* Insights */}
      {data.insights.length > 0 && (
        <div className="shrink-0 border-t p-3 max-h-40 overflow-y-auto">
          <h3 className="text-xs font-semibold mb-2">Insights</h3>
          <div className="space-y-1.5">
            {data.insights.map((insight, i) => (
              <div key={i} className="text-xs p-2 rounded bg-[var(--muted)]">
                <span className={`font-medium ${
                  insight.insight_type === "knowledge_gap" ? "text-orange-500" :
                  insight.insight_type === "bridge" ? "text-blue-500" :
                  "text-purple-500"
                }`}>
                  {insight.title}
                </span>
                <p className="text-[var(--muted-foreground)] mt-0.5">{insight.description}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function SvgGraph({ data, typeColors, communityColors, selectedNode, onSelectNode }: {
  data: GraphData
  typeColors: Record<string, string>
  communityColors: string[]
  selectedNode: string | null
  onSelectNode: (id: string | null) => void
}) {
  const width = 800
  const height = 600

  const positions = useMemo(() => {
    const pos = new Map<string, { x: number; y: number }>()
    const cx = width / 2
    const cy = height / 2
    const radius = Math.min(width, height) * 0.35

    data.nodes.forEach((node, i) => {
      const angle = (2 * Math.PI * i) / data.nodes.length
      pos.set(node.id, {
        x: cx + radius * Math.cos(angle),
        y: cy + radius * Math.sin(angle),
      })
    })
    return pos
  }, [data])

  const getColor = (node: typeof data.nodes[0]) => {
    if (node.community >= 0 && node.community < communityColors.length) {
      return communityColors[node.community]
    }
    return typeColors[node.node_type] || "#6b7280"
  }

  const getSize = (node: typeof data.nodes[0]) => {
    return Math.max(4, Math.min(16, Math.sqrt(node.size) * 4))
  }

  return (
    <svg width="100%" height="100%" viewBox={`0 0 ${width} ${height}`} className="w-full h-full">
      {/* Edges */}
      {data.edges.map((e, i) => {
        const src = positions.get(e.source)
        const tgt = positions.get(e.target)
        if (!src || !tgt) return null
        return (
          <line
            key={`edge-${i}`}
            x1={src.x} y1={src.y} x2={tgt.x} y2={tgt.y}
            stroke={e.weight > 2 ? "#94a3b8" : "#e2e8f0"}
            strokeWidth={Math.max(0.5, Math.min(3, e.weight * 0.5))}
            opacity={0.6}
          />
        )
      })}

      {/* Nodes */}
      {data.nodes.map((node) => {
        const pos = positions.get(node.id)
        if (!pos) return null
        const isSelected = selectedNode === node.id
        const color = getColor(node)
        const r = getSize(node) * (isSelected ? 1.5 : 1)

        return (
          <g key={`node-${node.id}`} onClick={() => onSelectNode(isSelected ? null : node.id)}
             className="cursor-pointer">
            <circle
              cx={pos.x} cy={pos.y} r={r}
              fill={color}
              stroke={isSelected ? "#000" : "#fff"}
              strokeWidth={isSelected ? 2 : 1}
              opacity={selectedNode && !isSelected ? 0.3 : 1}
            />
            <text
              x={pos.x} y={pos.y + r + 10}
              textAnchor="middle"
              fontSize={9}
              fill="var(--foreground)"
              opacity={selectedNode && !isSelected ? 0.3 : 1}
            >
              {node.label.length > 12 ? node.label.slice(0, 12) + "..." : node.label}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
