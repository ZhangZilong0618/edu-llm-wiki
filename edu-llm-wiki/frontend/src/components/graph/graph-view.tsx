// v2 entry: orchestrates the canvas, filter panel, node-detail sidebar,
// learning path panel and live event stream. State lives here so it can
// persist across view changes; each child component is dumb.

import { useEffect, useMemo, useState } from "react";
import { GitFork, RefreshCw } from "lucide-react";

import { useAppStore } from "@/stores/app-store";
import { api, type LearningPathResponse } from "@/lib/api";
import type { GraphData, GraphEdge, GraphNode } from "@/types/wiki";

import { GraphCanvas, type GraphHoverState, type GraphSelection } from "./graph-canvas";
import { GraphFilterPanel } from "./graph-filter-panel";
import { GraphMasteryBadge } from "./graph-mastery-badge";
import { useGraphData, type MasteryMap } from "./use-graph-data";
import { useGraphEvents } from "./use-graph-events";
import { DEFAULT_HIDDEN_TYPES, COMMUNITY_COLORS, type ColorMode } from "./constants";
import { groupNeighborsByNode, readableLabel } from "./utils";

export function GraphView() {
  const projectId = useAppStore((s) => s.currentProject) || "default";
  const compactLayout = useMediaQuery("(max-width: 980px)");

  const { data, mastery, loading, error, reload } = useGraphData({ projectId });
  const events = useGraphEvents(projectId);

  const [selected, setSelected] = useState<GraphSelection>(null);
  const [hover, setHover] = useState<GraphHoverState>(null);
  const [search, setSearch] = useState("");
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set(DEFAULT_HIDDEN_TYPES));
  const [showWeakLinks, setShowWeakLinks] = useState(false);
  const [colorMode, setColorMode] = useState<ColorMode>("type");
  const [nodeScale, setNodeScale] = useState(1);
  const [spacing, setSpacing] = useState(1);
  const [path, setPath] = useState<LearningPathResponse | null>(null);
  const [pathLoading, setPathLoading] = useState(false);

  const visibleNodes = useMemo<GraphNode[]>(() => {
    if (!data) return [];
    return data.nodes.filter((n) => !hiddenTypes.has(n.node_type || "unknown"));
  }, [data, hiddenTypes]);

  const nodesById = useMemo<Record<string, GraphNode>>(() => {
    const m: Record<string, GraphNode> = {};
    for (const n of data?.nodes || []) m[n.id] = n;
    return m;
  }, [data]);

  const selectedNodeData = useMemo(() => {
    if (!selected || !data) return null;
    const neighbors = groupNeighborsByNode(selected.node, data.edges, nodesById);
    return {
      node: selected.node,
      neighbors,
      degree: neighbors.length,
    };
  }, [selected, data, nodesById]);

  // Auto-load a learning path when the user selects a node they haven't
  // mastered yet. Skipped silently if mastery is still loading.
  useEffect(() => {
    if (!selected) return;
    const m = mastery[selected.node.id];
    if (m && (m.level === "proficient" || m.level === "mastered")) {
      setPath(null);
      return;
    }
    let cancelled = false;
    setPathLoading(true);
    api
      .getLearningPath(selected.node.id, 6)
      .then((res) => {
        if (!cancelled) setPath(res);
      })
      .catch(() => {
        if (!cancelled) setPath(null);
      })
      .finally(() => {
        if (!cancelled) setPathLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected, mastery]);

  if (loading && !data) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--muted-foreground)]">
        正在加载知识图谱…
      </div>
    );
  }
  if (error && !data) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-rose-500">
        加载失败：{error}
      </div>
    );
  }
  if (!data) return null;

  return (
    <div
      className={
        compactLayout
          ? "grid h-full min-h-0 min-w-0 grid-rows-[minmax(360px,1fr)_minmax(260px,38%)] overflow-hidden"
          : "grid h-full min-h-0 min-w-0 grid-cols-[minmax(520px,1fr)_360px] overflow-hidden xl:grid-cols-[minmax(640px,1fr)_390px]"
      }
    >
      <section className="relative min-h-0 min-w-0 overflow-hidden bg-[var(--background)]">
        <GraphCanvas
          data={data}
          selected={selected}
          hover={hover}
          searchQuery={search}
          hiddenTypes={hiddenTypes}
          colorMode={colorMode}
          communityColors={COMMUNITY_COLORS}
          nodeScale={nodeScale}
          spacing={spacing}
          showWeakLinks={showWeakLinks}
          onSelect={(id) => {
            const node = nodesById[id] || null;
            setSelected(node ? { node, degree: 0 } : null);
          }}
          onHover={setHover}
        />
        <div className="pointer-events-auto absolute left-2 right-2 top-2 flex flex-wrap items-center gap-2">
          <button
            onClick={reload}
            className="inline-flex shrink-0 items-center gap-1 rounded-md border bg-[var(--background)] px-2 py-1 text-xs shadow-sm"
            title="重新加载图谱"
          >
            <RefreshCw size={12} />
            刷新
          </button>
          <span className="min-w-0 rounded-md border bg-[var(--background)] px-2 py-1 text-[10px] text-[var(--muted-foreground)] shadow-sm">
            节点 {visibleNodes.length}/{data.nodes.length} · 边 {data.edges.length}
          </span>
        </div>
      </section>

      <aside
        className={`min-h-0 min-w-0 overflow-hidden bg-[var(--background)] ${
          compactLayout ? "border-t" : "border-l"
        }`}
      >
        <div className="flex h-full min-h-0 w-full flex-col overflow-y-auto p-3 text-[13px] sm:p-4">
          <GraphFilterPanel
            data={data}
            hiddenTypes={hiddenTypes}
            setHiddenTypes={setHiddenTypes}
            showWeakLinks={showWeakLinks}
            setShowWeakLinks={setShowWeakLinks}
            colorMode={colorMode}
            setColorMode={setColorMode}
            query={search}
            setQuery={setSearch}
            onReset={() => {
              setHiddenTypes(new Set(DEFAULT_HIDDEN_TYPES));
              setShowWeakLinks(false);
              setColorMode("type");
              setSearch("");
              setNodeScale(1);
              setSpacing(1);
            }}
          />

          {selectedNodeData && (
            <section className="mt-4 space-y-2 border-t pt-3">
              <div className="flex items-center gap-2">
                <h3 className="truncate text-sm font-semibold">{selectedNodeData.node.label}</h3>
                {mastery[selectedNodeData.node.id] && (
                  <GraphMasteryBadge level={mastery[selectedNodeData.node.id].level} />
                )}
              </div>
              <p className="text-[10px] text-[var(--muted-foreground)]">
                {selectedNodeData.node.node_type} · 邻居 {selectedNodeData.degree}
              </p>
              {selectedNodeData.neighbors.length > 0 && (
                <ul className="space-y-0.5 text-[11px]">
                  {selectedNodeData.neighbors.slice(0, 6).map((n) => (
                    <li
                      key={n.node.id}
                      className="flex items-center justify-between gap-1 truncate hover:underline"
                    >
                      <button
                        onClick={() => setSelected({ node: n.node, degree: 0 })}
                        className="truncate text-left"
                      >
                        {n.node.label}
                      </button>
                      <span className="shrink-0 text-[10px] text-[var(--muted-foreground)]">
                        {n.edgeType} · {n.weight.toFixed(1)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {selected && (
            <section className="mt-4 space-y-2 border-t pt-3">
              <div className="flex items-center gap-1 text-[10px] font-semibold uppercase text-[var(--muted-foreground)]">
                <GitFork size={10} /> 学习路径
              </div>
              {pathLoading ? (
                <p className="text-[11px] text-[var(--muted-foreground)]">计算中…</p>
              ) : path && path.steps.length > 0 ? (
                <ol className="space-y-1 text-[11px]">
                  {path.steps.map((step, i) => (
                    <li
                      key={step.node_id}
                      className="flex items-center gap-2 rounded border bg-[var(--muted)] px-1.5 py-1"
                    >
                      <span className="text-[10px] text-[var(--muted-foreground)]">{i + 1}.</span>
                      <span className="flex-1 truncate">
                        {readableLabel(step.title || step.node_id)}
                      </span>
                      {step.mastery && <GraphMasteryBadge level={step.mastery} />}
                    </li>
                  ))}
                  <li className="block pt-1 text-[10px] text-[var(--muted-foreground)]">
                    预计 {path.estimated_total_minutes.toFixed(0)} 分钟
                  </li>
                </ol>
              ) : (
                <p className="text-[11px] text-[var(--muted-foreground)]">无前置路径</p>
              )}
            </section>
          )}

          {events.length > 0 && (
            <section className="mt-4 space-y-1 border-t pt-3">
              <div className="text-[10px] font-semibold uppercase text-[var(--muted-foreground)]">
                实时事件
              </div>
              <ul className="space-y-0.5 text-[10px] text-[var(--muted-foreground)]">
                {events.slice(0, 5).map((e) => (
                  <li key={e.id}>
                    {e.event_type} · {new Date(e.created_at * 1000).toLocaleTimeString()}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </aside>
    </div>
  );
}

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);

  return matches;
}

function computeDegree(nodeId: string, edges: GraphEdge[]): number {
  let deg = 0;
  for (const e of edges) {
    if (e.source === nodeId || e.target === nodeId) deg++;
  }
  return deg;
}
