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
        <Network size={10} /> Article Graph Extraction
      </div>

      <div className="flex items-center gap-1.5 rounded-md border bg-[var(--background)] px-2 py-1.5">
        <Search size={12} className="text-[var(--muted-foreground)]" />
        <input
          value={pageFilter}
          onChange={(event) => setPageFilter(event.target.value)}
          placeholder="Filter articles…"
          className="flex-1 bg-transparent text-xs focus:outline-none"
        />
      </div>

      <select
        value={pagePath}
        onChange={(event) => onPagePathChange(event.target.value)}
        className="w-full rounded-md border bg-[var(--background)] px-2 py-1.5 text-xs"
        title="Select Wiki articles to extract a materials science relationship graph from"
      >
        <option value="">Select article…</option>
        {filteredPages.map((page) => (
          <option key={page.path} value={page.path}>
            {page.title || page.path}
          </option>
        ))}
      </select>

      <p className="text-[10px] text-[var(--muted-foreground)]">
        Articles {filteredPages.length} / {pages.length}
      </p>

      <div className="flex gap-1">
        <button
          type="button"
          onClick={onExtract}
          disabled={!pagePath || loading}
          className="inline-flex flex-1 items-center justify-center gap-1 rounded-md bg-[var(--primary)] px-2 py-1.5 text-[11px] text-[var(--primary-foreground)] disabled:opacity-50"
        >
          {loading ? <Loader2 size={11} className="animate-spin" /> : <FileSearch size={11} />}
          {loading ? "Extracting…" : "Extract Relationship Graph"}
        </button>
        {graph && (
          <button
            type="button"
            onClick={previewing ? onExitPreview : onPreview}
            className="inline-flex items-center gap-1 rounded-md border px-2 py-1.5 text-[11px]"
            title={previewing ? "Return to the full knowledge graph" : "Preview the article graph on the left canvas"}
          >
            {previewing ? <Undo2 size={11} /> : <Network size={11} />}
            {previewing ? "Back to Full Library" : "Preview"}
          </button>
        )}
      </div>

      {error && <p className="text-[11px] text-rose-500">Extraction failed: {error}</p>}

      {graph && (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-1 text-[10px]">
            <span className="rounded border px-1.5 py-1">
              {graph.stats.node_count} nodes
            </span>
            <span className="rounded border px-1.5 py-1">
              {graph.stats.edge_count} relations
            </span>
            <span className="rounded border px-1.5 py-1">
              {graph.stats.relation_candidate_count ?? graph.relation_candidates?.length ?? 0} candidates
            </span>
            <span className="rounded border px-1.5 py-1">
              {Math.round((graph.stats.relation_candidate_coverage ?? 0) * 100)}% coverage
            </span>
            <span className="rounded border px-1.5 py-1">
              {graph.stats.connected_components ?? "-"} components
            </span>
            <span className="rounded border px-1.5 py-1">
              {graph.stats.isolated_node_count ?? "-"} isolated
            </span>
          </div>

          <div>
            <p className="mb-1 text-[10px] font-semibold text-[var(--muted-foreground)]">
              Confirmed relation
            </p>
            <ul className="space-y-1 text-[10px]">
              {graph.edges.slice(0, 10).map((edge, index) => (
                <li key={`${edge.source}-${edge.target}-${index}`} className="rounded border px-1.5 py-1">
                  <span className="block truncate">
                    {label(edge.source)} → {label(edge.target)}
                  </span>
                  <span className="block truncate text-[var(--muted-foreground)]">
                    {edge.edge_type} · {edge.evidence || "No Evidence Yet"}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <details>
            <summary className="cursor-pointer text-[10px] font-semibold text-[var(--muted-foreground)]">
              Relation candidates ({graph.relation_candidates?.length || 0})
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
