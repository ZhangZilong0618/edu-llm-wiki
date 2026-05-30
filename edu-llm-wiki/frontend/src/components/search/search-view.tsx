import { useState } from "react"
import { useAppStore } from "@/stores/app-store"
import { api } from "@/lib/api"
import { Search, Loader2 } from "lucide-react"
import type { SearchResult } from "@/types/wiki"

export function SearchView() {
  const { searchQuery, setSearchQuery, searchResults, setSearchResults, isSearching, setIsSearching } = useAppStore()
  const setSelectedPage = useAppStore((s) => s.setSelectedPage)

  const handleSearch = async () => {
    if (!searchQuery.trim()) return
    setIsSearching(true)
    try {
      const resp = await api.search(searchQuery)
      setSearchResults(resp.results)
    } catch (e) {
      console.error(e)
    }
    setIsSearching(false)
  }

  const handleSelect = async (r: SearchResult) => {
    try {
      const page = await api.getPage(r.path)
      setSelectedPage(page)
    } catch {
      console.error("Failed to load page")
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="p-3 border-b">
        <div className="flex gap-2">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            placeholder="Search concepts, formulas, principles..."
            className="flex-1 rounded-lg border px-3 py-1.5 text-sm bg-[var(--background)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
          />
          <button
            onClick={handleSearch}
            disabled={isSearching}
            className="shrink-0 w-8 h-8 flex items-center justify-center rounded-lg bg-[var(--primary)] text-white disabled:opacity-50"
          >
            {isSearching ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {searchResults.map((r) => (
          <button
            key={r.path}
            onClick={() => handleSelect(r)}
            className="w-full text-left p-3 border-b hover:bg-[var(--accent)] transition-colors"
          >
            <div className="flex items-center gap-2">
              {r.title_match && (
                <span className="px-1.5 py-0.5 text-[9px] font-medium bg-yellow-100 text-yellow-800 rounded">
                  Title match
                </span>
              )}
              {r.vector_score != null && (
                <span className="px-1.5 py-0.5 text-[9px] font-medium bg-purple-100 text-purple-800 rounded">
                  Semantic
                </span>
              )}
            </div>
            <h3 className="text-sm font-medium mt-1">{r.title}</h3>
            <p className="text-xs text-[var(--muted-foreground)] mt-0.5 line-clamp-2">{r.snippet}</p>
            <p className="text-[10px] text-[var(--muted-foreground)] mt-1">{r.path} — score: {r.score.toFixed(1)}</p>
          </button>
        ))}
        {searchResults.length === 0 && !isSearching && (
          <p className="text-xs text-[var(--muted-foreground)] p-4">
            Enter a search query to find knowledge.
          </p>
        )}
      </div>
    </div>
  )
}
