import { create } from "zustand"
import type { SearchResult, WikiPage } from "@/types/wiki"

export type ActiveView = "wiki" | "sources" | "search" | "graph" | "lint" | "settings"

interface AppState {
  activeView: ActiveView
  setActiveView: (view: ActiveView) => void

  // Selected page for preview
  selectedPage: WikiPage | null
  setSelectedPage: (page: WikiPage | null) => void

  // Search
  searchQuery: string
  setSearchQuery: (q: string) => void
  searchResults: SearchResult[]
  setSearchResults: (results: SearchResult[]) => void
  isSearching: boolean
  setIsSearching: (v: boolean) => void

  // Sources
  sourceFiles: { name: string; size: number; modified: number }[]
  setSourceFiles: (files: { name: string; size: number; modified: number }[]) => void

  // Ingest progress
  ingestStatus: string
  setIngestStatus: (s: string) => void

  // Knowledge tree pages
  wikiPages: { path: string; title: string; type: string; summary: string }[]
  setWikiPages: (pages: { path: string; title: string; type: string; summary: string }[]) => void
}

export const useAppStore = create<AppState>((set) => ({
  activeView: "wiki",
  setActiveView: (view) => set({ activeView: view }),

  selectedPage: null,
  setSelectedPage: (page) => set({ selectedPage: page }),

  searchQuery: "",
  setSearchQuery: (q) => set({ searchQuery: q }),
  searchResults: [],
  setSearchResults: (results) => set({ searchResults: results }),
  isSearching: false,
  setIsSearching: (v) => set({ isSearching: v }),

  sourceFiles: [],
  setSourceFiles: (files) => set({ sourceFiles: files }),

  ingestStatus: "",
  setIngestStatus: (s) => set({ ingestStatus: s }),

  wikiPages: [],
  setWikiPages: (pages) => set({ wikiPages: pages }),
}))
