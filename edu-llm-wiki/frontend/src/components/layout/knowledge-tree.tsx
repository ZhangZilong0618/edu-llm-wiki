import { useState } from "react"
import { useAppStore } from "@/stores/app-store"
import { api } from "@/lib/api"
import { ChevronDown, ChevronRight, FileText, Hash, Sigma, Scale3D, Pencil, BookOpen, FolderOpen } from "lucide-react"

const typeIcons: Record<string, React.ReactNode> = {
  concept: <Hash size={14} />,
  formula: <Sigma size={14} />,
  principle: <Scale3D size={14} />,
  exercise: <Pencil size={14} />,
  source: <FileText size={14} />,
  synthesis: <BookOpen size={14} />,
}

const typeColors: Record<string, string> = {
  concept: "#3b82f6",
  formula: "#8b5cf6",
  principle: "#f59e0b",
  exercise: "#10b981",
  source: "#6b7280",
  synthesis: "#ec4899",
}

const TYPE_ORDER = ["concept", "formula", "principle", "exercise", "source", "synthesis", "query", "system"]

export function KnowledgeTree() {
  const wikiPages = useAppStore((s) => s.wikiPages)
  const selectedPage = useAppStore((s) => s.selectedPage)
  const setSelectedPage = useAppStore((s) => s.setSelectedPage)
  const setActiveView = useAppStore((s) => s.setActiveView)
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
    exercise: "Exercises",
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
      setSelectedPage({ path: p.path, title: p.title, page_type: p.type, content: "", sources: [], tags: [], created: "", updated: "" })
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
    <div className="flex flex-col h-full overflow-y-auto p-2">
      <h2 className="text-xs font-semibold text-[var(--muted-foreground)] uppercase px-2 py-1 mb-1">
        Knowledge Wiki
      </h2>
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
                  className="w-full text-left px-4 py-1 text-sm rounded hover:bg-[var(--accent)] transition-colors truncate"
                  style={{
                    color: selectedPage?.path === p.path ? "var(--primary)" : "var(--sidebar-foreground)",
                    fontWeight: selectedPage?.path === p.path ? 500 : 400,
                  }}
                >
                  {p.title}
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
  )
}
