// Filter panel: per-type visibility toggles, weak-link toggle, search box,
// colour-mode toggle (type vs community). Kept dumb — all state lives in
// the parent so it can be persisted across view changes.

import { Search, Filter, Layers, Tag, RotateCcw } from "lucide-react"

import {
  COMMUNITY_COLORS,
  DEFAULT_HIDDEN_TYPES,
  TYPE_COLORS,
  TYPE_LABELS,
  type ColorMode,
} from "./constants"
import { readableLabel } from "./utils"
import type { GraphData, GraphNode } from "@/types/wiki"

interface Props {
  data: GraphData
  hiddenTypes: Set<string>
  setHiddenTypes: (next: Set<string>) => void
  showWeakLinks: boolean
  setShowWeakLinks: (next: boolean) => void
  colorMode: ColorMode
  setColorMode: (next: ColorMode) => void
  query: string
  setQuery: (next: string) => void
  onReset: () => void
}

export function GraphFilterPanel(props: Props) {
  const {
    data,
    hiddenTypes,
    setHiddenTypes,
    showWeakLinks,
    setShowWeakLinks,
    colorMode,
    setColorMode,
    query,
    setQuery,
    onReset,
  } = props

  const types = Array.from(new Set(data.nodes.map((n) => n.node_type || "unknown")))
  const visibleNodes = data.nodes.filter((n) => !hiddenTypes.has(n.node_type || "unknown"))
  const matchedNodes = query
    ? data.nodes.filter((n) => {
        const q = query.toLowerCase()
        return (
          n.label.toLowerCase().includes(q) || (n.node_type || "").toLowerCase().includes(q)
        )
      })
    : visibleNodes

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5 rounded-md border bg-[var(--background)] px-2 py-1.5">
        <Search size={12} className="text-[var(--muted-foreground)]" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索节点…"
          className="flex-1 bg-transparent text-xs focus:outline-none"
        />
      </div>

      <div>
        <div className="mb-1 flex items-center gap-1 text-[10px] font-semibold uppercase text-[var(--muted-foreground)]">
          <Filter size={10} /> 类型
        </div>
        <div className="flex flex-wrap gap-1">
          {types.map((t) => {
            const checked = !hiddenTypes.has(t)
            return (
              <button
                key={t}
                onClick={() => {
                  const next = new Set(hiddenTypes)
                  if (checked) next.add(t)
                  else next.delete(t)
                  setHiddenTypes(next)
                }}
                className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] transition-colors ${
                  checked
                    ? "border-transparent bg-[var(--muted)] text-[var(--foreground)]"
                    : "border-dashed text-[var(--muted-foreground)] line-through"
                }`}
              >
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ background: TYPE_COLORS[t] || "#94a3b8" }}
                />
                {TYPE_LABELS[t] || t}
              </button>
            )
          })}
        </div>
      </div>

      <div>
        <div className="mb-1 flex items-center gap-1 text-[10px] font-semibold uppercase text-[var(--muted-foreground)]">
          弱连接
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={showWeakLinks}
            onChange={(e) => setShowWeakLinks(e.target.checked)}
          />
          <span>显示非强连接边 (weight &lt; 8)</span>
        </label>
      </div>

      <div>
        <div className="mb-1 flex items-center gap-1 text-[10px] font-semibold uppercase text-[var(--muted-foreground)]">
          配色
        </div>
        <div className="flex gap-1">
          <button
            onClick={() => setColorMode("type")}
            className={`flex-1 rounded border px-2 py-1 text-[10px] ${
              colorMode === "type"
                ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]"
                : ""
            }`}
          >
            <Tag size={10} className="mr-1 inline" />类型
          </button>
          <button
            onClick={() => setColorMode("community")}
            className={`flex-1 rounded border px-2 py-1 text-[10px] ${
              colorMode === "community"
                ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]"
                : ""
            }`}
          >
            <Layers size={10} className="mr-1 inline" />社区
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between border-t pt-2 text-[10px] text-[var(--muted-foreground)]">
        <span>
          可见 {matchedNodes.length} / {data.nodes.length} 节点
        </span>
        <button onClick={onReset} className="inline-flex items-center gap-1 hover:text-[var(--foreground)]">
          <RotateCcw size={10} />重置
        </button>
      </div>
    </div>
  )
}
