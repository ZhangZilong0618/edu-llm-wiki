import { create } from "zustand"
import type { SearchResult, WikiPage } from "@/types/wiki"

export type ActiveView = "wiki" | "sources" | "search" | "graph" | "lint" | "settings"

export interface IngestProgress {
  filename: string
  stages: {
    stage: string
    message: string
    status: "pending" | "active" | "done"
    details?: { concepts?: string[]; formulas?: string[]; principles?: string[]; exercises?: string[] }
    pages?: { current: number; total: number; items: { title: string; page_type: string; action: string }[] }
    created?: number
    updated?: number
  }[]
  error?: string
}

interface AppState {
  activeView: ActiveView
  setActiveView: (view: ActiveView) => void

  // Project management
  projects: { name: string; title: string }[]
  setProjects: (list: { name: string; title: string }[]) => void
  currentProject: string
  setCurrentProject: (name: string) => void

  // Selected page for preview
  selectedPage: WikiPage | null
  setSelectedPage: (page: WikiPage | null) => void
  selectPage: (path: string) => Promise<void>

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
  ingestProgress: IngestProgress | null
  setIngestProgress: (p: IngestProgress | null) => void
  updateIngestProgress: (fn: (prev: IngestProgress | null) => IngestProgress | null) => void

  // Knowledge tree pages
  wikiPages: { path: string; title: string; type: string; summary: string }[]
  setWikiPages: (pages: { path: string; title: string; type: string; summary: string }[]) => void

  // Conversations
  conversations: { id: string; title: string; message_count: number; created: string; updated: string }[]
  setConversations: (list: { id: string; title: string; message_count: number; created: string; updated: string }[]) => void
  currentConversationId: string | null
  setCurrentConversationId: (id: string | null) => void
}

export const useAppStore = create<AppState>((set, get) => ({
  activeView: "wiki",
  setActiveView: (view) => set({ activeView: view }),

  projects: [],
  setProjects: (list) => set({ projects: list }),
  currentProject: "default",
  setCurrentProject: (name) => set({ currentProject: name }),

  selectedPage: null,
  setSelectedPage: (page) => set({ selectedPage: page }),
  selectPage: async (path: string) => {
    try {
      const { api } = await import("@/lib/api")
      const page = await api.getPage(path)
      set({ selectedPage: page })
    } catch {
      set({ selectedPage: null })
    }
  },

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
  ingestProgress: null,
  setIngestProgress: (p) => set({ ingestProgress: p }),
  updateIngestProgress: (fn) => set((s) => ({ ingestProgress: fn(s.ingestProgress) })),

  wikiPages: [],
  setWikiPages: (pages) => set({ wikiPages: pages }),

  conversations: [],
  setConversations: (list) => set({ conversations: list }),
  currentConversationId: null,
  setCurrentConversationId: (id) => set({ currentConversationId: id }),
}))
