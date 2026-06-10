import type { WikiPage, SearchResponse, GraphData, GraphInsight, ChatResponse, IngestResult, Project } from "@/types/wiki"

const BASE = "/api"
const PROJECT_STORAGE_KEY = "edu-llm-wiki.currentProject"

let _projectId = typeof window === "undefined"
  ? "default"
  : window.localStorage.getItem(PROJECT_STORAGE_KEY) || "default"

export function setProjectId(id: string) {
  _projectId = id
  if (typeof window !== "undefined") {
    window.localStorage.setItem(PROJECT_STORAGE_KEY, id)
  }
}

function p() {
  return `project_id=${encodeURIComponent(_projectId)}`
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const { headers: optHeaders, ...rest } = options || {}
  const res = await fetch(url, {
    ...rest,
    headers: { "Content-Type": "application/json", ...optHeaders },
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
  // Projects
  listProjects: () => request<Project[]>(`${BASE}/projects`),
  createProject: (name: string) =>
    request<Project>(`${BASE}/projects`, { method: "POST", body: JSON.stringify({ name }) }),
  deleteProject: (name: string) =>
    request<{ status: string }>(`${BASE}/projects/${encodeURIComponent(name)}`, { method: "DELETE" }),

  // Sources
  uploadFile: async (file: File) => {
    const form = new FormData()
    form.append("file", file)
    const res = await fetch(`${BASE}/ingest/upload?${p()}`, { method: "POST", body: form })
    if (!res.ok) {
      const text = await res.text()
      throw new Error(`Upload failed: ${res.status} ${text}`)
    }
    return res.json() as Promise<{ filename: string; size: number }>
  },
  runIngest: (sourcePaths: string[], force = false) =>
    request<IngestResult>(`${BASE}/ingest/run?${p()}`, {
      method: "POST",
      body: JSON.stringify({ source_paths: sourcePaths, force }),
    }),
  runIngestStream: async function* (sourcePaths: string[], force = false) {
    const res = await fetch(`${BASE}/ingest/run-stream?${p()}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_paths: sourcePaths, force }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    if (!res.body) throw new Error("No response body")
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ""
    while (true) {
      let done: boolean, value: Uint8Array | undefined
      try {
        ({ done, value } = await reader.read())
      } catch {
        // Connection reset — stream ended abruptly
        break
      }
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split("\n")
      buf = lines.pop() || ""
      for (const line of lines) {
        if (line.startsWith("data: ")) {
          const data = line.slice(6)
          if (data === "[DONE]") return
          try {
            yield JSON.parse(data)
          } catch { /* skip malformed lines */ }
        }
      }
    }
  },
  runIngestBatch: async function* (sourcePaths: string[], force = false, concurrency = 3) {
    const res = await fetch(`${BASE}/ingest/run-batch?${p()}&concurrency=${concurrency}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_paths: sourcePaths, force }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    if (!res.body) throw new Error("No response body")
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ""
    while (true) {
      let done: boolean, value: Uint8Array | undefined
      try {
        ({ done, value } = await reader.read())
      } catch {
        break
      }
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split("\n")
      buf = lines.pop() || ""
      for (const line of lines) {
        if (line.startsWith("data: ")) {
          const data = line.slice(6)
          if (data === "[DONE]") return
          try {
            yield JSON.parse(data)
          } catch { /* skip malformed lines */ }
        }
      }
    }
  },
  listSources: () => request<FileEntry[]>(`${BASE}/ingest/sources?${p()}`),
  deleteSource: (filename: string) =>
    request<{ status: string }>(`${BASE}/ingest/sources/${encodeURIComponent(filename)}?${p()}`, { method: "DELETE" }),
  deleteSourceWiki: (filename: string) =>
    request<{ status: string; source: string; deleted_pages: string[]; deleted_count: number; cache_deleted: boolean }>(
      `${BASE}/ingest/sources/${encodeURIComponent(filename)}/wiki?${p()}`,
      { method: "DELETE" }
    ),
  viewSourceUrl: (filename: string) =>
    `${BASE}/ingest/sources/${encodeURIComponent(filename)}/view?${p()}`,
  parseSource: (filename: string) =>
    request<{ filename: string; content: string; images: string[]; extension: string; view_url: string | null }>(`${BASE}/ingest/sources/${encodeURIComponent(filename)}/parsed?${p()}`),
  mediaUrl: (filename: string) =>
    `${BASE}/ingest/media/${encodeURIComponent(filename)}?${p()}`,

  // Wiki
  listPages: () => request<WikiPageSummary[]>(`${BASE}/wiki/pages?${p()}`),
  getPage: (path: string) => request<WikiPage>(`${BASE}/wiki/pages/${encodeURIComponent(path)}?${p()}`),
  createPage: (data: { title: string; page_type: string; content: string; sources?: string[]; tags?: string[] }) =>
    request<{ path: string; full_path: string; title: string }>(`${BASE}/wiki/pages?${p()}`, { method: "POST", body: JSON.stringify(data) }),
  updatePage: (path: string, data: Record<string, unknown>) =>
    request<{ path: string; status: string }>(`${BASE}/wiki/pages/${encodeURIComponent(path)}?${p()}`, { method: "PUT", body: JSON.stringify(data) }),
  deletePage: (path: string) =>
    request<{ path: string; status: string }>(`${BASE}/wiki/pages/${encodeURIComponent(path)}?${p()}`, { method: "DELETE" }),
  getPurpose: () => request<{ content: string }>(`${BASE}/wiki/system/purpose?${p()}`),
  updatePurpose: (content: string) =>
    request<{ status: string }>(`${BASE}/wiki/system/purpose?${p()}`, { method: "PUT", body: JSON.stringify({ content }) }),
  getSchema: () => request<{ content: string }>(`${BASE}/wiki/system/schema?${p()}`),
  updateSchema: (content: string) =>
    request<{ status: string }>(`${BASE}/wiki/system/schema?${p()}`, { method: "PUT", body: JSON.stringify({ content }) }),

  // Search
  search: (q: string, vector = false, topK = 20) =>
    request<SearchResponse>(
      `${BASE}/search?q=${encodeURIComponent(q)}&vector=${vector}&top_k=${topK}&${p()}`
    ),

  // Graph
  getGraph: () => request<GraphData>(`${BASE}/graph?${p()}`),
  getNeighborhood: (nodeId: string, depth = 1) =>
    request<{ nodes: unknown[]; edges: unknown[] }>(`${BASE}/graph/neighborhood/${encodeURIComponent(nodeId)}?depth=${depth}&${p()}`),
  getInsights: () => request<GraphInsight[]>(`${BASE}/graph/insights?${p()}`),

  // Chat
  chat: (messages: { role: string; content: string }[], options?: Record<string, unknown>) =>
    request<ChatResponse>(`${BASE}/chat?${p()}`, {
      method: "POST",
      body: JSON.stringify({ messages, ...options }),
    }),
  chatStream: async function* (messages: { role: string; content: string }[], signal?: AbortSignal, options?: Record<string, unknown>) {
    const res = await fetch(`${BASE}/chat/stream?${p()}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages, ...options }),
      signal,
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    if (!res.body) throw new Error("No response body")
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ""
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split("\n")
      buf = lines.pop() || ""
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue
        const data = line.slice(6)
        if (data === "[DONE]") return
        try {
          yield JSON.parse(data)
        } catch {
          // skip malformed SSE lines
        }
      }
    }
  },
  recognizeChatImage: async (file: File) => {
    const form = new FormData()
    form.append("file", file)
    const res = await fetch(`${BASE}/chat/image-ocr?${p()}`, { method: "POST", body: form })
    if (!res.ok) {
      const text = await res.text()
      throw new Error(`Image recognition failed: ${res.status} ${text}`)
    }
    return res.json() as Promise<{ filename: string; content_type: string; text: string }>
  },

  // Conversations
  listConversations: () => request<{ id: string; title: string; message_count: number; created: string; updated: string }[]>(`${BASE}/conversations?${p()}`),
  getConversation: (id: string) => request<{ id: string; title: string; messages: any[] }>(`${BASE}/conversations/${id}?${p()}`),
  saveConversation: (conv: { id: string; title: string; messages: any[] }) =>
    request<{ status: string; id: string }>(`${BASE}/conversations?${p()}`, {
      method: "POST",
      body: JSON.stringify(conv),
    }),
  deleteConversation: (id: string) =>
    request<{ status: string }>(`${BASE}/conversations/${id}?${p()}`, { method: "DELETE" }),

  // Exercises
  checkExercise: (data: {
    question: string
    student_answer: string
    reference_answer?: string | null
    page_title?: string
    page_path?: string
    context?: string
  }) =>
    request<{
      level: "empty" | "weak" | "partial" | "good"
      title: string
      detail: string
      matched: string[]
      missing: string[]
      evidence: string[]
      suggested_answer?: string | null
      source: string
    }>(`${BASE}/exercises/check?${p()}`, { method: "POST", body: JSON.stringify(data) }),
  completeExerciseSolution: (data: { page_path: string; note?: string }) =>
    request<{ status: string; solution: string; page: WikiPage }>(
      `${BASE}/exercises/complete-solution?${p()}`,
      { method: "POST", body: JSON.stringify(data) }
    ),

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
  getPaddleocrSettings: () => request<PaddleocrSettings>(`${BASE}/settings/paddleocr`),
  savePaddleocrSettings: (data: PaddleocrSettings) =>
    request<{ status: string }>(`${BASE}/settings/paddleocr`, { method: "PUT", body: JSON.stringify(data) }),

  // PaddleOCR document parsing
  startParse: (filename: string) =>
    request<ParseStatus>(`${BASE}/ingest/sources/${encodeURIComponent(filename)}/parse?${p()}`, { method: "POST" }),
  getParseStatus: (filename: string) =>
    request<ParseStatus>(`${BASE}/ingest/sources/${encodeURIComponent(filename)}/parse-status?${p()}`),
  getAllParseStatuses: () =>
    request<ParseStatus[]>(`${BASE}/ingest/parse-statuses?${p()}`),
  parseAllPending: () =>
    request<{ status: string; files: ParseStatus[] }>(`${BASE}/ingest/parse-all-pending?${p()}`, { method: "POST" }),
  getParsedDoc: (filename: string) =>
    request<{ filename: string; content: string }>(`${BASE}/ingest/sources/${encodeURIComponent(filename)}/parsed-doc?${p()}`),

  // Deep research
  runResearch: (data: { page_path: string; action: string; note?: string }) =>
    request<{ action: string; title: string; content: string; related_pages: WikiPageSummary[] }>(
      `${BASE}/research/run?${p()}`,
      { method: "POST", body: JSON.stringify(data) }
    ),
  saveResearchNote: (data: { page_path: string; title: string; content: string }) =>
    request<{ status: string; page: WikiPage }>(
      `${BASE}/research/save-note?${p()}`,
      { method: "POST", body: JSON.stringify(data) }
    ),

  // Tests
  listTests: () => request<TestSummary[]>(`${BASE}/tests?${p()}`),
  createTest: (data: TestCreateRequest) =>
    request<TestSession>(`${BASE}/tests?${p()}`, { method: "POST", body: JSON.stringify(data) }),
  getTest: (id: string) => request<TestSession>(`${BASE}/tests/${encodeURIComponent(id)}?${p()}`),
  submitTest: (id: string, answers: Record<string, string | string[]>) =>
    request<TestSession>(`${BASE}/tests/${encodeURIComponent(id)}/submit?${p()}`, {
      method: "POST",
      body: JSON.stringify({ answers }),
    }),
  deleteTest: (id: string) =>
    request<{ status: string; id: string }>(`${BASE}/tests/${encodeURIComponent(id)}?${p()}`, { method: "DELETE" }),
}

export interface LlmSettings {
  llm_provider: string
  llm_api_key: string
  llm_model: string
  llm_base_url: string
  llm_max_tokens: number
  llm_temperature: number
  generation_language: "zh" | "en"
}

export interface EmbeddingSettings {
  embedding_enabled: boolean
  embedding_endpoint: string
  embedding_api_key: string
  embedding_model: string
}

export interface PaddleocrSettings {
  paddleocr_token: string
  paddleocr_model: string
  paddleocr_orientation: boolean
  paddleocr_unwarping: boolean
  paddleocr_chart: boolean
}

export interface ParseStatus {
  filename: string
  status: "not_started" | "pending" | "running" | "done" | "failed"
  page_count: number
  image_count: number
  error: string | null
  markdown_path: string | null
  job_id?: string
}

export interface TestCreateRequest {
  title?: string
  scope: "wiki" | "source"
  source?: string | null
  question_count: number
  question_types: string[]
  difficulty: string
  mode: string
  /** Optional seed echoed into the LLM prompt to encourage diversity
   *  across consecutive generations. Frontend auto-fills this. */
  seed?: string
}

export interface TestQuestion {
  id: string
  type: "multiple_choice" | "fill_blank" | "short_answer"
  prompt: string
  options: string[]
  blanks: number
  answer: string | string[]
  explanation: string
  related_page: string | null
  concepts: string[]
  difficulty: string
}

export interface TestAttempt {
  question_id: string
  user_answer: string | string[]
  score: number
  max_score: number
  level: "empty" | "weak" | "partial" | "good"
  feedback: string
  correct_answer: string | string[]
}

export interface TestSession {
  id: string
  title: string
  scope: string
  source: string | null
  mode: string
  difficulty: string
  status: "active" | "submitted"
  questions: TestQuestion[]
  attempts: TestAttempt[]
  score: number | null
  max_score: number | null
  created_at: string
  submitted_at: string | null
}

export interface TestSummary {
  id: string
  title: string
  status: "active" | "submitted"
  question_count: number
  score: number | null
  max_score: number | null
  created_at: string
  submitted_at: string | null
}
