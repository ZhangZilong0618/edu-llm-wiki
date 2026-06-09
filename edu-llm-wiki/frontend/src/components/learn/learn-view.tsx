import { useEffect, useState, useMemo } from "react"
import {
  GraduationCap,
  RefreshCw,
  BookOpen,
  FlaskConical,
  Lightbulb,
  Dumbbell,
  FileText,
  Layers,
  ArrowRight,
  AlertTriangle,
  Star,
  ChevronRight,
  Play,
} from "lucide-react"
import { api } from "@/lib/api"
import { useAppStore } from "@/stores/app-store"
import type { GraphData, GraphNode } from "@/types/wiki"

const TYPE_CONFIG: Record<string, { icon: React.ElementType; color: string; bg: string; label: string }> = {
  concept: { icon: BookOpen, color: "text-blue-600", bg: "bg-blue-50 dark:bg-blue-950/30", label: "Concept" },
  formula: { icon: FlaskConical, color: "text-violet-600", bg: "bg-violet-50 dark:bg-violet-950/30", label: "Formula" },
  principle: { icon: Lightbulb, color: "text-amber-600", bg: "bg-amber-50 dark:bg-amber-950/30", label: "Principle" },
  exercise: { icon: Dumbbell, color: "text-emerald-600", bg: "bg-emerald-50 dark:bg-emerald-950/30", label: "Exercise" },
  source: { icon: FileText, color: "text-gray-500", bg: "bg-gray-50 dark:bg-gray-950/30", label: "Source" },
  synthesis: { icon: Layers, color: "text-pink-600", bg: "bg-pink-50 dark:bg-pink-950/30", label: "Synthesis" },
}

interface PathStep {
  node: GraphNode
  prerequisites: string[]
  depth: number
  isBridge: boolean
  isGap: boolean
}

function topologicalSort(nodes: GraphNode[], edges: { source: string; target: string; edge_type: string; weight: number }[]): PathStep[] {
  // Only use prerequisite edges for learning path
  const prereqEdges = edges.filter((e) => e.edge_type === "prerequisite")
  const nodeMap = new Map(nodes.map((n) => [n.id, n]))

  // If no prerequisite edges exist, return all nodes as flat list (no ordering)
  if (prereqEdges.length === 0) {
    return nodes.map((node) => ({
      node,
      prerequisites: [],
      depth: 0,
      isBridge: false,
      isGap: false,
    }))
  }

  // Build adjacency: for each node, what are its prerequisites (incoming edges)
  const prereqOf = new Map<string, Set<string>>()
  const dependents = new Map<string, Set<string>>()
  const inDegree = new Map<string, number>()

  for (const n of nodes) {
    prereqOf.set(n.id, new Set())
    dependents.set(n.id, new Set())
    inDegree.set(n.id, 0)
  }

  for (const e of prereqEdges) {
    if (nodeMap.has(e.source) && nodeMap.has(e.target)) {
      // e.source is a prerequisite of e.target
      prereqOf.get(e.target)!.add(e.source)
      dependents.get(e.source)!.add(e.target)
      inDegree.set(e.target, (inDegree.get(e.target) ?? 0) + 1)
    }
  }

  // Kahn's algorithm
  const queue: string[] = []
  for (const [id, deg] of inDegree) {
    if (deg === 0) queue.push(id)
  }
  queue.sort((a, b) => {
    const ta = nodeMap.get(a)?.node_type ?? ""
    const tb = nodeMap.get(b)?.node_type ?? ""
    const order = ["concept", "formula", "principle", "exercise", "synthesis", "source"]
    return order.indexOf(ta) - order.indexOf(tb)
  })

  const result: PathStep[] = []
  const visited = new Set<string>()
  const depthMap = new Map<string, number>()

  while (queue.length > 0) {
    const id = queue.shift()!
    if (visited.has(id)) continue
    visited.add(id)

    const node = nodeMap.get(id)!
    const prereqs = [...(prereqOf.get(id) ?? [])]
    const depth = prereqs.length === 0 ? 0 : Math.max(...prereqs.map((p) => (depthMap.get(p) ?? 0) + 1))
    depthMap.set(id, depth)

    result.push({
      node,
      prerequisites: prereqs.map((p) => nodeMap.get(p)?.label ?? p),
      depth,
      isBridge: false,
      isGap: false,
    })

    // Add dependents whose prerequisites are all visited
    for (const dep of dependents.get(id) ?? []) {
      const deg = (inDegree.get(dep) ?? 1) - 1
      inDegree.set(dep, deg)
      if (deg === 0) {
        queue.push(dep)
      }
    }
  }

  // Add any remaining nodes (cycles or disconnected)
  for (const n of nodes) {
    if (!visited.has(n.id)) {
      result.push({
        node: n,
        prerequisites: [],
        depth: 0,
        isBridge: false,
        isGap: false,
      })
    }
  }

  return result
}

function buildSteps(data: GraphData): PathStep[] {
  const steps = topologicalSort(data.nodes, data.edges)

  // Mark bridge and gap nodes
  const bridgeIds = new Set<string>()
  const gapIds = new Set<string>()
  for (const insight of data.insights) {
    if (insight.insight_type === "bridge") {
      insight.node_ids.forEach((id) => bridgeIds.add(id))
    }
    if (insight.insight_type === "knowledge_gap" || insight.insight_type === "isolated") {
      insight.node_ids.forEach((id) => gapIds.add(id))
    }
  }

  return steps.map((s) => ({
    ...s,
    isBridge: bridgeIds.has(s.node.id),
    isGap: gapIds.has(s.node.id),
  }))
}

export function LearnView() {
  const [data, setData] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const selectPage = useAppStore((s) => s.selectPage)

  useEffect(() => {
    api.getGraph()
      .then(setData)
      .catch((e) => setError(e?.message || "Failed to load"))
      .finally(() => setLoading(false))
  }, [])

  const steps = useMemo(() => (data ? buildSteps(data) : []), [data])

  // Group by depth for display
  const levels = useMemo(() => {
    const map = new Map<number, PathStep[]>()
    for (const s of steps) {
      if (!map.has(s.depth)) map.set(s.depth, [])
      map.get(s.depth)!.push(s)
    }
    return [...map.entries()].sort((a, b) => a[0] - b[0])
  }, [steps])

  // Stats
  const stats = useMemo(() => {
    const types: Record<string, number> = {}
    for (const s of steps) {
      types[s.node.node_type] = (types[s.node.node_type] ?? 0) + 1
    }
    return types
  }, [steps])

  if (loading) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-[var(--muted-foreground)]">
        <RefreshCw className="h-8 w-8 animate-spin opacity-40" />
        <p className="text-sm">Building learning path...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-[var(--muted-foreground)]">
        <GraduationCap className="h-10 w-10 opacity-30" />
        <p className="text-sm text-red-500">{error}</p>
      </div>
    )
  }

  if (steps.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-center text-[var(--muted-foreground)]">
        <div>
          <GraduationCap className="h-12 w-12 mx-auto mb-3 opacity-20" />
          <p className="text-sm font-medium">No learning path available</p>
          <p className="text-xs mt-1">Import documents and run ingest to generate knowledge.</p>
        </div>
      </div>
    )
  }

  // Check if we have prerequisite edges for meaningful ordering
  const hasPrereqs = data?.edges.some((e) => e.edge_type === "prerequisite") ?? false

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="shrink-0 border-b px-4 py-3">
        <div className="flex items-center gap-2 mb-2">
          <GraduationCap className="h-4 w-4 text-[var(--muted-foreground)]" />
          <span className="text-sm font-medium">Learning Path</span>
          <span className="text-xs text-[var(--muted-foreground)] ml-auto">{steps.length} steps</span>
        </div>
        {!hasPrereqs && steps.length > 0 && (
          <p className="text-[11px] text-amber-600 bg-amber-50 dark:bg-amber-950/20 px-2 py-1 rounded">
            Learning order is approximate (based on topic type). Re-ingest documents to generate prerequisite relationships.
          </p>
        )}
        {/* Stats bar */}
        <div className="flex flex-wrap gap-1.5 mt-2">
          {Object.entries(stats).map(([type, count]) => {
            const cfg = TYPE_CONFIG[type] ?? TYPE_CONFIG.concept
            const Icon = cfg.icon
            return (
              <span key={type} className={`inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded ${cfg.bg} ${cfg.color}`}>
                <Icon className="h-3 w-3" />
                {count} {cfg.label}{count > 1 ? "s" : ""}
              </span>
            )
          })}
        </div>
      </div>

      {/* Path content */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {levels.map(([level, levelSteps], levelIdx) => (
          <div key={level} className="mb-6">
            {/* Level header */}
            <div className="flex items-center gap-2 mb-3">
              <div className="flex items-center justify-center w-6 h-6 rounded-full bg-[var(--primary)] text-[var(--primary-foreground)] text-xs font-bold">
                {levelIdx + 1}
              </div>
              <span className="text-xs font-medium text-[var(--muted-foreground)]">
                {level === 0 ? "Foundation" : level === 1 ? "Core Concepts" : level === 2 ? "Advanced" : `Level ${level}`}
              </span>
              {levelIdx < levels.length - 1 && (
                <ArrowRight className="h-3 w-3 text-[var(--muted-foreground)] ml-auto" />
              )}
            </div>

            {/* Steps in this level */}
            <div className="space-y-2 ml-3 pl-4 border-l-2 border-[var(--border)]">
              {levelSteps.map((step) => {
                const cfg = TYPE_CONFIG[step.node.node_type] ?? TYPE_CONFIG.concept
                const Icon = cfg.icon
                const isExercise = step.node.node_type === "exercise"
                return (
                  <div
                    key={step.node.id}
                    className="w-full text-left group rounded-lg border p-3 hover:bg-[var(--accent)] transition-colors"
                  >
                    <button
                      onClick={() => selectPage(step.node.id)}
                      className="w-full text-left"
                    >
                      <div className="flex items-start gap-2.5">
                        <div className={`shrink-0 mt-0.5 w-7 h-7 rounded-md flex items-center justify-center ${cfg.bg}`}>
                          <Icon className={`h-3.5 w-3.5 ${cfg.color}`} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className="text-sm font-medium truncate group-hover:text-[var(--primary)] transition-colors">
                              {step.node.label}
                            </span>
                            {step.isBridge && (
                              <span className="shrink-0 inline-flex items-center gap-0.5 text-[10px] px-1 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-600">
                                <Star className="h-2.5 w-2.5" />
                                Key
                              </span>
                            )}
                            {step.isGap && (
                              <span className="shrink-0 inline-flex items-center gap-0.5 text-[10px] px-1 py-0.5 rounded bg-orange-100 dark:bg-orange-900/30 text-orange-600">
                                <AlertTriangle className="h-2.5 w-2.5" />
                                Gap
                              </span>
                            )}
                          </div>
                          {step.prerequisites.length > 0 && (
                            <div className="flex items-center gap-1 mt-1 flex-wrap">
                              <span className="text-[10px] text-[var(--muted-foreground)]">Requires:</span>
                              {step.prerequisites.map((p, i) => (
                                <span key={i} className="text-[10px] bg-[var(--muted)] px-1 py-0.5 rounded">
                                  {p}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                        <ChevronRight className="h-3.5 w-3.5 text-[var(--muted-foreground)] opacity-0 group-hover:opacity-100 transition-opacity shrink-0 mt-1" />
                      </div>
                    </button>
                    {isExercise && (
                      <button
                        onClick={() => {
                          useAppStore.getState().setActiveView("chat")
                          useAppStore.getState().selectPage(step.node.id)
                        }}
                        className="mt-2 flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-md bg-emerald-500 text-white hover:bg-emerald-600 transition-colors"
                      >
                        <Play className="h-3 w-3" />
                        Practice
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
