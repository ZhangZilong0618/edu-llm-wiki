export interface WikiPage {
  path: string
  title: string
  page_type: string
  content: string
  sources: string[]
  tags: string[]
  created: string
  updated: string
  // --- v2 structured fields (all optional, backward compatible) ---
  difficulty: number | null
  prerequisites: string[]
  related: string[]
  common_misconceptions: string[]
  worked_example_ref: string[]
  last_reviewed: string
}

export interface GraphNode {
  id: string
  label: string
  node_type: string
  size: number
  community: number
  metadata: Record<string, unknown>
}

export interface GraphEdge {
  source: string
  target: string
  edge_type: string
  weight: number
}

export interface GraphInsight {
  insight_type: "isolated" | "bridge" | "surprising_connection" | "knowledge_gap"
  title: string
  description: string
  node_ids: string[]
  score: number
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  communities: { id: number; label: string; cohesion: number; member_count: number; top_node: string }[]
  insights: GraphInsight[]
}

export interface SearchResult {
  path: string
  title: string
  snippet: string
  score: number
  title_match: boolean
  vector_score: number | null
}

export interface SearchResponse {
  mode: string
  results: SearchResult[]
  token_hits: number
  vector_hits: number
}

export interface ChatMessage {
  role: "user" | "assistant" | "system"
  content: string
}

export interface CitedPage {
  path: string
  title: string
  snippet: string
}

export interface ChatResponse {
  content: string
  cited_pages: CitedPage[]
  conversation_id: string
}

export interface FileEntry {
  name: string
  size: number
  modified: number
}

export interface Project {
  name: string
  title: string
}

export interface IngestResult {
  source: string
  status: string
  wiki_pages_created: string[]
  wiki_pages_updated: string[]
  concepts_extracted: string[]
  error: string
}
