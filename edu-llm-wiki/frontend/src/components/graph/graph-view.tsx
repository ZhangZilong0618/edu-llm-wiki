// v2 entry: orchestrates the canvas, filter panel, node-detail sidebar,
// learning path panel and live event stream. State lives here so it can
// persist across view changes; each child component is dumb.

import { useEffect, useMemo, useState, useCallback } from "react";
import { BookOpen, GitFork, RefreshCw, X } from "lucide-react";

import { useAppStore } from "@/stores/app-store";
import { api, type LearningPathResponse } from "@/lib/api";
import type { GraphData, GraphEdge, GraphNode } from "@/types/wiki";

import { GraphNetworkCanvas, type GraphHoverState, type GraphSelection } from "./graph-network-canvas";
import { GraphFilterPanel } from "./graph-filter-panel";
import { GraphMasteryBadge } from "./graph-mastery-badge";
import { useGraphData, type MasteryMap } from "./use-graph-data";
import { useGraphEvents } from "./use-graph-events";
import { DEFAULT_HIDDEN_TYPES, COMMUNITY_COLORS, type ColorMode } from "./constants";
import { groupNeighborsByNode, readableLabel } from "./utils";

export function GraphView() {
  const projectId = useAppStore((s) => s.currentProject) || "default";
  const setSelectedPage = useAppStore((s) => s.setSelectedPage);
  const setActiveView = useAppStore((s) => s.setActiveView);
  const compactLayout = useMediaQuery("(max-width: 980px)");

  const { data, mastery, loading, error, reload } = useGraphData({ projectId });
  const events = useGraphEvents(projectId);

  const [selected, setSelected] = useState<GraphSelection>(null);
  const [hover, setHover] = useState<GraphHoverState>(null);
  const [search, setSearch] = useState("");
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set(DEFAULT_HIDDEN_TYPES));
  const [showWeakLinks, setShowWeakLinks] = useState(true);
  const [colorMode, setColorMode] = useState<ColorMode>("type");
  const [nodeScale, setNodeScale] = useState(1);
  const [spacing, setSpacing] = useState(1);
  const [path, setPath] = useState<LearningPathResponse | null>(null);
  const [pathLoading, setPathLoading] = useState(false);
  const [nodeDetail, setNodeDetail] = useState<{ text: string; loading: boolean } | null>(null);

  const visibleNodes = useMemo<GraphNode[]>(() => {
    if (!data) return [];
    return data.nodes.filter((n) => !hiddenTypes.has(n.node_type || "unknown"));
  }, [data, hiddenTypes]);

  const nodesById = useMemo<Record<string, GraphNode>>(() => {
    const m: Record<string, GraphNode> = {};
    for (const n of data?.nodes || []) m[n.id] = n;
    return m;
  }, [data]);

  const openNodeInWiki = useCallback(async (node: GraphNode) => {
    const path = typeof node.metadata?.path === "string" ? node.metadata.path : null
    if (!path) return
    setActiveView("wiki")
    try {
      const page = await api.getPage(path)
      setSelectedPage(page)
    } catch {
      setSelectedPage({ path, title: node.label, page_type: node.node_type || "unknown", content: "", sources: [], tags: [], created: "", updated: "", difficulty: null, prerequisites: [], related: [], common_misconceptions: [], worked_example_ref: [], last_reviewed: "" })
    }
  }, [setActiveView, setSelectedPage])

  const selectedNodeData = useMemo(() => {
    if (!selected || !data) return null;
    const neighbors = groupNeighborsByNode(selected.node, data.edges, nodesById);
    return {
      node: selected.node,
      neighbors,
      degree: neighbors.length,
    };
  }, [selected, data, nodesById]);

  // Clicking a graph node only shows an inline description. It never changes
  // the active app view, so users can explore without losing the graph.
  useEffect(() => {
    if (!selectedNodeData) {
      setNodeDetail(null);
      return;
    }
    const node = selectedNodeData.node;
    const localDescription = ["description", "definition", "summary"]
      .map((key) => (typeof node.metadata?.[key] === "string" ? node.metadata[key] as string : ""))
      .find((value) => value.trim());
    if (localDescription) {
      setNodeDetail({ text: cleanNodeDescription(localDescription), loading: false });
      return;
    }

    const pagePath = typeof node.metadata?.path === "string" ? node.metadata.path : null;
    if (!pagePath) {
      setNodeDetail({ text: "暂无节点描述。", loading: false });
      return;
    }

    let cancelled = false;
    setNodeDetail({ text: "", loading: true });
    api.getPage(pagePath)
      .then((page) => {
        if (!cancelled) setNodeDetail({ text: cleanNodeDescription(page.content), loading: false });
      })
      .catch(() => {
        if (!cancelled) setNodeDetail({ text: "暂无节点描述。", loading: false });
      });
    return () => { cancelled = true; };
  }, [selectedNodeData]);

  // A graph rebuild can remove the selected page (for example after generated
  // wiki pages are deleted). Clear both the selection and its learning path so
  // the sidebar never continues to display a route to a nonexistent node.
  useEffect(() => {
    if (!data || !selected) return;
    if (!nodesById[selected.node.id]) {
      setSelected(null);
      setPath(null);
    }
  }, [data, nodesById, selected]);

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
        <GraphNetworkCanvas
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
          onSelect={(id: string) => {
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

        {selectedNodeData && (
          <div className="pointer-events-auto absolute bottom-4 right-4 z-10 w-[min(380px,calc(100%-2rem))] rounded-xl border bg-white/95 shadow-xl backdrop-blur">
            <div className="flex items-start justify-between gap-2 border-b px-3 py-2">
              <div className="min-w-0">
                <h3 className="truncate text-sm font-semibold">{selectedNodeData.node.label}</h3>
                <p className="mt-0.5 text-[10px] text-[var(--muted-foreground)]">
                  {selectedNodeData.node.node_type} · 邻居 {selectedNodeData.degree}
                </p>
              </div>
              <button
                onClick={() => setSelected(null)}
                className="rounded p-1 text-slate-500 hover:bg-slate-100"
                title="关闭"
              >
                <X size={14} />
              </button>
            </div>
            <div className="max-h-40 overflow-y-auto px-3 py-2 text-[12px] leading-5 text-slate-700">
              {nodeDetail?.loading ? "正在加载描述…" : nodeDetail?.text || "暂无节点描述。"}
            </div>
            {typeof selectedNodeData.node.metadata?.path === "string" && (
              <div className="border-t px-3 py-2">
                <button
                  onClick={() => void openNodeInWiki(selectedNodeData.node)}
                  className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] text-slate-700 hover:bg-slate-100"
                >
                  <BookOpen size={12} />
                  在 Wiki 中打开
                </button>
              </div>
            )}
          </div>
        )}
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
                        onClick={() => {
                          setSelected({ node: n.node, degree: 0 });
                        }}
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


function cleanNodeDescription(content: string): string {
  const withoutRefs = (content || "")
    .replace(/\[ref:[^\]]+\]/g, "")
    .replace(/\{\{[^}]+\}\}/g, "")
    .trim();

  const definitionMatch = withoutRefs.match(/^##\s*定义\s*\n?([\s\S]*?)(?=\n##\s|$)/im);
  const explanationMatch = withoutRefs.match(/^##\s*(?:解释|说明)\s*\n?([\s\S]*?)(?=\n##\s|$)/im);
  const paragraph = (definitionMatch?.[1] || explanationMatch?.[1] || withoutRefs)
    .replace(/^#+\s*/gm, "")
    .replace(/\n+/g, " ")
    .replace(/\s{2,}/g, " ")
    .trim();

  return paragraph.length > 360 ? `${paragraph.slice(0, 360)}…` : paragraph || "暂无节点描述。";
}
