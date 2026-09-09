import { create } from "zustand"
import type { SearchResult, WikiPage } from "@/types/wiki"

export type ActiveView = "wiki" | "sources" | "search" | "graph" | "settings" | "learn" | "chat" | "tests"

const PROJECT_STORAGE_KEY = "edu-llm-wiki.currentProject"
const ACTIVE_VIEW_STORAGE_KEY = "edu-llm-wiki.activeView"
const ACTIVE_VIEWS: ActiveView[] = ["wiki", "sources", "search", "graph", "settings", "learn", "chat", "tests"]

function initialProject(): string {
  if (typeof window === "undefined") return "default"
  return window.localStorage.getItem(PROJECT_STORAGE_KEY) || "default"
}

function initialActiveView(): ActiveView {
  if (typeof window === "undefined") return "wiki"
  const saved = window.localStorage.getItem(ACTIVE_VIEW_STORAGE_KEY)
  if (saved === "search" || saved === "lint") return "wiki"
  return ACTIVE_VIEWS.includes(saved as ActiveView) ? (saved as ActiveView) : "wiki"
}

export interface IngestProgress {
  filename: string
  status: "running" | "done" | "error"
  error?: string
  stages: {
    stage: string
    message: string
    status: "pending" | "active" | "done"
    details?: { concepts?: string[]; formulas?: string[]; principles?: string[] }
    logs?: string
    pages?: { current: number; total: number; items: { title: string; page_type: string; action: string }[] }
    created?: number
    updated?: number
  }[]
}

export interface OperationState {
  label: string
  startedAt: number
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

  // Pending cross-view requests: a page-scoped "generate a test for this page"
  // hop from PreviewPanel's footer button. Consumed by TestsView on mount.
  pendingTestPagePath: string | null
  setPendingTestPagePath: (path: string | null) => void

  // Search
  searchQuery: string
  setSearchQuery: (q: string) => void
  searchResults: SearchResult[]
  setSearchResults: (results: SearchResult[]) => void
  isSearching: boolean
  setIsSearching: (v: boolean) => void

  // Sources
  sourceFiles: { name: string; size: number; modified: number; imported?: boolean }[]
  setSourceFiles: (files: { name: string; size: number; modified: number; imported?: boolean }[]) => void

  // Ingest progress
  ingestStatus: string
  setIngestStatus: (s: string) => void
  ingestProgress: IngestProgress | null
  setIngestProgress: (p: IngestProgress | null) => void
  updateIngestProgress: (fn: (prev: IngestProgress | null) => IngestProgress | null) => void

  // Long-running UI operations survive view switches.
  operations: Record<string, OperationState>
  beginOperation: (key: string, label?: string) => void
  endOperation: (key: string) => void

  // Per-page research notes/results should survive preview unmounts.
  researchStates: Record<string, unknown>
  updateResearchState: (path: string, patch: Record<string, unknown>, initial?: Record<string, unknown>) => void

  // Knowledge tree pages
  wikiPages: {
    path: string
    title: string
    type: string
    summary: string
    difficulty?: number | null
    prerequisites?: string[]
    related?: string[]
    common_misconceptions?: string[]
    worked_example_ref?: string[]
    last_reviewed?: string
  }[]
  setWikiPages: (pages: {
    path: string
    title: string
    type: string
    summary: string
    difficulty?: number | null
    prerequisites?: string[]
    related?: string[]
    common_misconceptions?: string[]
    worked_example_ref?: string[]
    last_reviewed?: string
  }[]) => void

  // Conversations
  conversations: { id: string; title: string; message_count: number; created: string; updated: string }[]
  setConversations: (list: { id: string; title: string; message_count: number; created: string; updated: string }[]) => void
  currentConversationId: string | null
  setCurrentConversationId: (id: string | null) => void

  // Source preview
  selectedSource: { filename: string; content: string; images: string[]; extension: string; view_url: string | null } | null
  setSelectedSource: (s: { filename: string; content: string; images: string[]; extension: string; view_url: string | null } | null) => void

  // Source file selected in Import view (filename only, for the dual-pane preview)
  importSelectedSource: string | null
  setImportSelectedSource: (name: string | null) => void
}

export const useAppStore = create<AppState>((set, get) => ({
  activeView: initialActiveView(),
  setActiveView: (view) => {
    const nextView = view === "search" ? "wiki" : view
    if (typeof window !== "undefined") {
      window.localStorage.setItem(ACTIVE_VIEW_STORAGE_KEY, nextView)
    }
    set({ activeView: nextView })
  },

  projects: [],
  setProjects: (list) => set({ projects: list }),
  currentProject: initialProject(),
  setCurrentProject: (name) => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(PROJECT_STORAGE_KEY, name)
    }
    set({ currentProject: name })
  },

  selectedPage: null,
  setSelectedPage: (page) => set({ selectedPage: page }),
  selectPage: async (path: string) => {
    try {
      const { api } = await import("@/lib/api")
      let page = await api.getPage(path).catch(() => null)
      if (!page && !path.endsWith(".md")) {
        page = await api.getPage(path + ".md").catch(() => null)
      }
      set({ selectedPage: page, selectedSource: null })
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

  operations: {},
  beginOperation: (key, label = "处理中") => set((s) => ({
    operations: {
      ...s.operations,
      [key]: { label, startedAt: Date.now() },
    },
  })),
  endOperation: (key) => set((s) => {
    const next = { ...s.operations }
    delete next[key]
    return { operations: next }
  }),

  researchStates: {},
  updateResearchState: (path, patch, initial = {}) => set((s) => ({
    researchStates: {
      ...s.researchStates,
      [path]: {
        ...(s.researchStates[path] as Record<string, unknown> | undefined || initial),
        ...patch,
      },
    },
  })),

  wikiPages: [],
  setWikiPages: (pages) => set({ wikiPages: pages }),

  pendingTestPagePath: null,
  setPendingTestPagePath: (path) => set({ pendingTestPagePath: path }),

  conversations: [],
  setConversations: (list) => set({ conversations: list }),
  currentConversationId: null,
  setCurrentConversationId: (id) => set({ currentConversationId: id }),

  selectedSource: null,
  setSelectedSource: (s) => set({ selectedSource: s }),

  importSelectedSource: null,
  setImportSelectedSource: (name) => set({ importSelectedSource: name }),
}))
