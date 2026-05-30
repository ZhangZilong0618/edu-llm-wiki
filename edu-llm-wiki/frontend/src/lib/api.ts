import type { WikiPage, SearchResponse, GraphData, GraphInsight, ChatResponse, IngestResult } from "@/types/wiki"

const BASE = "/api"

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`HTTP ${res.status}: ${text}`)
  }
  return res.json()
}

type FileEntry = { name: string; size: number; modified: number }
type WikiPageSummary = { path: string; title: string; type: string; summary: string }

export const api = {
  // Sources
  uploadFile: async (file: File) => {
    const form = new FormData()
    form.append("file", file)
    const res = await fetch(`${BASE}/ingest/upload`, { method: "POST", body: form })
    return res.json() as Promise<{ filename: string; size: number }>
  },
  runIngest: (sourcePaths: string[], force = false) =>
    request<IngestResult>(`${BASE}/ingest/run`, {
      method: "POST",
      body: JSON.stringify({ source_paths: sourcePaths, force }),
    }),
  listSources: () => request<FileEntry[]>(`${BASE}/ingest/sources`),
  deleteSource: (filename: string) =>
    request<{ status: string }>(`${BASE}/ingest/sources/${encodeURIComponent(filename)}`, { method: "DELETE" }),

  // Wiki
  listPages: () => request<WikiPageSummary[]>(`${BASE}/wiki/pages`),
  getPage: (path: string) => request<WikiPage>(`${BASE}/wiki/pages/${encodeURIComponent(path)}`),
  createPage: (data: { title: string; page_type: string; content: string; sources?: string[]; tags?: string[] }) =>
    request<{ path: string; full_path: string; title: string }>(`${BASE}/wiki/pages`, { method: "POST", body: JSON.stringify(data) }),
  updatePage: (path: string, data: Record<string, unknown>) =>
    request<{ path: string; status: string }>(`${BASE}/wiki/pages/${encodeURIComponent(path)}`, { method: "PUT", body: JSON.stringify(data) }),
  deletePage: (path: string) =>
    request<{ path: string; status: string }>(`${BASE}/wiki/pages/${encodeURIComponent(path)}`, { method: "DELETE" }),
  getPurpose: () => request<{ content: string }>(`${BASE}/wiki/system/purpose`),
  updatePurpose: (content: string) =>
    request<{ status: string }>(`${BASE}/wiki/system/purpose`, { method: "PUT", body: JSON.stringify({ content }) }),
  getSchema: () => request<{ content: string }>(`${BASE}/wiki/system/schema`),
  updateSchema: (content: string) =>
    request<{ status: string }>(`${BASE}/wiki/system/schema`, { method: "PUT", body: JSON.stringify({ content }) }),

  // Search
  search: (q: string, vector = false, topK = 20) =>
    request<SearchResponse>(
      `${BASE}/search?q=${encodeURIComponent(q)}&vector=${vector}&top_k=${topK}`
    ),

  // Graph
  getGraph: () => request<GraphData>(`${BASE}/graph`),
  getNeighborhood: (nodeId: string, depth = 1) =>
    request<{ nodes: unknown[]; edges: unknown[] }>(`${BASE}/graph/neighborhood/${encodeURIComponent(nodeId)}?depth=${depth}`),
  getInsights: () => request<GraphInsight[]>(`${BASE}/graph/insights`),

  // Chat
  chat: (messages: { role: string; content: string }[]) =>
    request<ChatResponse>(`${BASE}/chat`, {
      method: "POST",
      body: JSON.stringify({ messages }),
    }),

  // Lint
  runLint: () => request<Record<string, unknown>>(`${BASE}/lint/run`, { method: "POST" }),

  // Health
  health: () => request<{ status: string; version: string }>(`${BASE}/health`),

  // Settings
  getLlmSettings: () => request<LlmSettings>(`${BASE}/settings/llm`),
  saveLlmSettings: (data: LlmSettings) =>
    request<{ status: string }>(`${BASE}/settings/llm`, { method: "PUT", body: JSON.stringify(data) }),
  testLlmConnection: (data: LlmSettings) =>
    request<{ ok: boolean; message: string }>(`${BASE}/settings/llm/test`, { method: "POST", body: JSON.stringify(data) }),
  getEmbeddingSettings: () => request<EmbeddingSettings>(`${BASE}/settings/embedding`),
  saveEmbeddingSettings: (data: EmbeddingSettings) =>
    request<{ status: string }>(`${BASE}/settings/embedding`, { method: "PUT", body: JSON.stringify(data) }),
}

export interface LlmSettings {
  llm_provider: string
  llm_api_key: string
  llm_model: string
  llm_base_url: string
  llm_max_tokens: number
  llm_temperature: number
}

export interface EmbeddingSettings {
  embedding_enabled: boolean
  embedding_endpoint: string
  embedding_api_key: string
  embedding_model: string
}
