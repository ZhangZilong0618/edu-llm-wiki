import { useState } from "react"
import { useAppStore } from "@/stores/app-store"
import { api } from "@/lib/api"
import { toast } from "@/components/ui/toast"
import { ChevronDown, ChevronRight, FileText, Hash, Sigma, Scale3D, BookOpen, FolderOpen, Loader2, Search, X } from "lucide-react"
import type { SearchResult } from "@/types/wiki"
import { displayWikiTitle } from "@/lib/wiki-title"
import { PageBadges } from "@/lib/page-badges"

const typeIcons: Record<string, React.ReactNode> = {
  concept: <Hash size={14} />,
  formula: <Sigma size={14} />,
  principle: <Scale3D size={14} />,
  source: <FileText size={14} />,
  synthesis: <BookOpen size={14} />,
}

const typeColors: Record<string, string> = {
  concept: "#3b82f6",
  formula: "#8b5cf6",
  principle: "#f59e0b",
  source: "#6b7280",
  synthesis: "#ec4899",
}

const TYPE_ORDER = ["concept", "formula", "principle", "source", "synthesis", "query", "system"]

export function KnowledgeTree() {
  const wikiPages = useAppStore((s) => s.wikiPages)
  const selectedPage = useAppStore((s) => s.selectedPage)
  const setSelectedPage = useAppStore((s) => s.setSelectedPage)
  const setActiveView = useAppStore((s) => s.setActiveView)
  const { searchQuery, setSearchQuery, searchResults, setSearchResults, isSearching, setIsSearching } = useAppStore()
  const [collapsedTypes, setCollapsedTypes] = useState<Set<string>>(() => new Set(["source"]))

  const grouped: Record<string, typeof wikiPages> = {}
  for (const p of wikiPages) {
    const t = p.type || "unknown"
    if (!grouped[t]) grouped[t] = []
    grouped[t].push(p)
  }

  const typeLabels: Record<string, string> = {
    concept: "Concepts",
    formula: "Formulas",
    principle: "Principles",
    source: "Imported",
    synthesis: "Synthesis",
    query: "Q&A",
    system: "System",
  }

  const handleSelect = async (p: typeof wikiPages[0]) => {
    try {
      const page = await api.getPage(p.path)
      useAppStore.getState().setSelectedSource(null)
      setSelectedPage(page)
      setActiveView("wiki")
    } catch {
      setSelectedPage({ path: p.path, title: p.title, page_type: p.type, content: "", sources: [], tags: [], created: "", updated: "", difficulty: null, prerequisites: [], related: [], common_misconceptions: [], worked_example_ref: [], last_reviewed: "" })
    }
  }

  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      setSearchResults([])
      return
    }
    setIsSearching(true)
    try {
      const resp = await api.search(searchQuery)
      setSearchResults(resp.results)
    } catch (e: any) {
      toast({ type: "error", message: e?.message || "Search failed" })
    } finally {
      setIsSearching(false)
    }
  }

  const clearSearch = () => {
    setSearchQuery("")
    setSearchResults([])
  }

  const handleSearchSelect = async (r: SearchResult) => {
    try {
      const page = await api.getPage(r.path)
      useAppStore.getState().setSelectedSource(null)
      setSelectedPage(page)
      setActiveView("wiki")
    } catch {
      toast({ type: "error", message: "Failed to load page" })
    }
  }

  const toggleType = (type: string) => {
    setCollapsedTypes((prev) => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="shrink-0 border-b p-2">
        <h2 className="mb-2 px-2 py-1 text-xs font-semibold uppercase text-[var(--muted-foreground)]">
          Knowledge Wiki
        </h2>
        <div className="flex gap-1.5">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted-foreground)]" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              placeholder="Search wiki..."
              className="h-8 w-full rounded-md border bg-[var(--background)] pl-7 pr-7 text-xs focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
            />
            {searchQuery && (
              <button
                onClick={clearSearch}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
                title="Clear search"
              >
                <X size={12} />
              </button>
            )}
          </div>
          <button
            onClick={handleSearch}
            disabled={isSearching || !searchQuery.trim()}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-[var(--primary)] text-[var(--primary-foreground)] disabled:opacity-50"
            title="Search"
          >
            {isSearching ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />}
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
      {(searchQuery || searchResults.length > 0) && (
        <div className="mb-3 rounded-md border bg-[var(--background)]">
          <div className="flex items-center gap-2 border-b px-2 py-1.5">
            <span className="text-xs font-medium">Search Results</span>
            <span className="ml-auto text-[10px] text-[var(--muted-foreground)]">
              {isSearching ? "Searching..." : `${searchResults.length} found`}
            </span>
          </div>
          <div className="max-h-72 overflow-y-auto">
            {searchResults.map((r) => (
              <button
                key={r.path}
                onClick={() => handleSearchSelect(r)}
                className="w-full border-b px-2 py-2 text-left last:border-b-0 hover:bg-[var(--accent)]"
              >
                <div className="flex items-center gap-1">
                  {r.title_match && (
                    <span className="rounded bg-yellow-100 px-1.5 py-0.5 text-[9px] font-medium text-yellow-800">
                      Title
                    </span>
                  )}
                  {r.vector_score != null && (
                    <span className="rounded bg-purple-100 px-1.5 py-0.5 text-[9px] font-medium text-purple-800">
                      Semantic
                    </span>
                  )}
                </div>
                <h3 className="mt-1 truncate text-xs font-medium">{r.title}</h3>
                <p className="mt-0.5 line-clamp-2 text-[11px] text-[var(--muted-foreground)]">{r.snippet}</p>
              </button>
            ))}
            {searchResults.length === 0 && !isSearching && (
              <p className="px-2 py-3 text-xs text-[var(--muted-foreground)]">
                Press Enter to search this wiki.
              </p>
            )}
          </div>
        </div>
      )}

      {[...TYPE_ORDER, ...Object.keys(grouped).filter((type) => !TYPE_ORDER.includes(type))].map((type) => {
        const pages = grouped[type] || []
        const collapsed = collapsedTypes.has(type)
        return (
          <div key={type} className="mb-3">
            <button
              onClick={() => toggleType(type)}
              className="flex w-full items-center gap-1 px-2 py-1 text-xs font-medium text-[var(--muted-foreground)] rounded hover:bg-[var(--accent)] transition-colors"
            >
              {collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
              <span style={{ color: typeColors[type] || "#6b7280" }}>
                {typeIcons[type] || <FileText size={14} />}
              </span>
              <span>{typeLabels[type] || type}</span>
              <span className="ml-auto text-[10px] opacity-50">{pages.length}</span>
            </button>
            {!collapsed && (
              pages.length > 0 ? pages.map((p) => (
                <button
                  key={p.path}
                  onClick={() => handleSelect(p)}
                  className="flex w-full items-center gap-1.5 px-4 py-1 text-sm rounded hover:bg-[var(--accent)] transition-colors"
                  style={{
                    color: selectedPage?.path === p.path ? "var(--primary)" : "var(--sidebar-foreground)",
                    fontWeight: selectedPage?.path === p.path ? 500 : 400,
                  }}
                >
                  <span className="truncate flex-1 text-left">{displayWikiTitle(p)}</span>
                  <PageBadges
                    difficulty={p.difficulty}
                    prerequisiteCount={p.prerequisites?.length}
                    misconceptionCount={p.common_misconceptions?.length}
                    lastReviewed={p.last_reviewed}
                  />
                </button>
              )) : (
                <p className="px-4 py-1 text-xs text-[var(--muted-foreground)] opacity-60">No pages yet</p>
              )
            )}
          </div>
        )
      })}
      {wikiPages.length === 0 && (
        <div className="p-3 space-y-3">
          <p className="text-xs text-[var(--muted-foreground)]">
            No pages yet. Upload documents and let the LLM build your knowledge base.
          </p>
          <button
            onClick={() => setActiveView("sources")}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-[var(--primary)] text-[var(--primary-foreground)] text-sm font-medium hover:opacity-90 transition-opacity"
          >
            <FolderOpen size={16} />
            Import Documents
          </button>
        </div>
      )}
      </div>
    </div>
  )
}
