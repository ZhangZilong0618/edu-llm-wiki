import { useState } from "react";
import { FileSearch, Loader2, Network, Search, Undo2 } from "lucide-react";

import type { MaterialsGraphData } from "@/lib/api";

export interface MaterialsPageOption {
  path: string;
  title: string;
  type: string;
  summary?: string;
}

interface Props {
  pages: MaterialsPageOption[];
  pagePath: string;
  onPagePathChange: (path: string) => void;
  onExtract: () => void;
  loading: boolean;
  error: string | null;
  graph: MaterialsGraphData | null;
  previewing: boolean;
  onPreview: () => void;
  onExitPreview: () => void;
}

export function MaterialsGraphPanel(props: Props) {
  const {
    pages,
    pagePath,
    onPagePathChange,
    onExtract,
    loading,
    error,
    graph,
    previewing,
    onPreview,
    onExitPreview,
  } = props;

  const [pageFilter, setPageFilter] = useState("");
  const labels = new Map((graph?.nodes || []).map((node) => [node.id, node.label]));
  const label = (id: string) => labels.get(id) || id;
  const normalizedFilter = pageFilter.trim().toLowerCase();
  const filteredPages = normalizedFilter
    ? pages.filter((page) =>
        `${page.title} ${page.path} ${page.type}`.toLowerCase().includes(normalizedFilter),
      )
    : pages;

  return (
    <section className="mt-4 space-y-2 border-t pt-3">
      <div className="flex items-center gap-1 text-[10px] font-semibold uppercase text-[var(--muted-foreground)]">
        <Network size={10} /> 文章图谱抽取
      </div>

      <div className="flex items-center gap-1.5 rounded-md border bg-[var(--background)] px-2 py-1.5">
        <Search size={12} className="text-[var(--muted-foreground)]" />
        <input
          value={pageFilter}
          onChange={(event) => setPageFilter(event.target.value)}
          placeholder="过滤文章…"
          className="flex-1 bg-transparent text-xs focus:outline-none"
        />
      </div>

      <select
        value={pagePath}
        onChange={(event) => onPagePathChange(event.target.value)}
        className="w-full rounded-md border bg-[var(--background)] px-2 py-1.5 text-xs"
        title="选择要抽取材料学关系图谱的 Wiki 文章"
      >
        <option value="">选择文章…</option>
        {filteredPages.map((page) => (
          <option key={page.path} value={page.path}>
            {page.title || page.path}
          </option>
        ))}
      </select>

      <p className="text-[10px] text-[var(--muted-foreground)]">
        可选文章 {filteredPages.length} / {pages.length}
      </p>

      <div className="flex gap-1">
        <button
          type="button"
          onClick={onExtract}
          disabled={!pagePath || loading}
          className="inline-flex flex-1 items-center justify-center gap-1 rounded-md bg-[var(--primary)] px-2 py-1.5 text-[11px] text-[var(--primary-foreground)] disabled:opacity-50"
        >
          {loading ? <Loader2 size={11} className="animate-spin" /> : <FileSearch size={11} />}
          {loading ? "抽取中…" : "抽取关系图谱"}
        </button>
        {graph && (
          <button
            type="button"
            onClick={previewing ? onExitPreview : onPreview}
            className="inline-flex items-center gap-1 rounded-md border px-2 py-1.5 text-[11px]"
            title={previewing ? "返回全库知识图谱" : "在左侧画布预览文章图谱"}
          >
            {previewing ? <Undo2 size={11} /> : <Network size={11} />}
            {previewing ? "返回全库" : "预览"}
          </button>
        )}
      </div>

      {error && <p className="text-[11px] text-rose-500">抽取失败：{error}</p>}

      {graph && (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-1 text-[10px]">
            <span className="rounded border px-1.5 py-1">
              节点 {graph.stats.node_count}
            </span>
            <span className="rounded border px-1.5 py-1">
              关系 {graph.stats.edge_count}
            </span>
            <span className="rounded border px-1.5 py-1">
              候选 {graph.stats.relation_candidate_count ?? graph.relation_candidates?.length ?? 0}
            </span>
            <span className="rounded border px-1.5 py-1">
              覆盖 {Math.round((graph.stats.relation_candidate_coverage ?? 0) * 100)}%
            </span>
            <span className="rounded border px-1.5 py-1">
              连通分量 {graph.stats.connected_components ?? "-"}
            </span>
            <span className="rounded border px-1.5 py-1">
              孤立节点 {graph.stats.isolated_node_count ?? "-"}
            </span>
          </div>

          <div>
            <p className="mb-1 text-[10px] font-semibold text-[var(--muted-foreground)]">
              已确认关系
            </p>
            <ul className="space-y-1 text-[10px]">
              {graph.edges.slice(0, 10).map((edge, index) => (
                <li key={`${edge.source}-${edge.target}-${index}`} className="rounded border px-1.5 py-1">
                  <span className="block truncate">
                    {label(edge.source)} → {label(edge.target)}
                  </span>
                  <span className="block truncate text-[var(--muted-foreground)]">
                    {edge.edge_type} · {edge.evidence || "暂无证据"}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <details>
            <summary className="cursor-pointer text-[10px] font-semibold text-[var(--muted-foreground)]">
              关系候选（{graph.relation_candidates?.length || 0}）
            </summary>
            <ul className="mt-1 space-y-1 text-[10px]">
              {(graph.relation_candidates || []).slice(0, 12).map((candidate, index) => (
                <li key={`${candidate.source}-${candidate.target}-${index}`} className="rounded border px-1.5 py-1">
                  <span className="block truncate">
                    {label(candidate.source)} → {label(candidate.target)}
                  </span>
                  <span className="block truncate text-[var(--muted-foreground)]">
                    {candidate.edge_type} · score {candidate.score.toFixed(2)} ·{" "}
                    {candidate.evidence || candidate.reason}
                  </span>
                </li>
              ))}
            </ul>
          </details>
        </div>
      )}
    </section>
  );
}
