// Static colour & label tables shared by the graph canvas and the
// filter/legend panels. Keep the keys in sync with backend node_type values.

export const TYPE_COLORS: Record<string, string> = {
  concept: "#3b82f6",
  formula: "#8b5cf6",
  principle: "#f59e0b",
  exercise: "#10b981",
  source: "#6b7280",
  synthesis: "#ec4899",
  query: "#06b6d4",
}

export const TYPE_LABELS: Record<string, string> = {
  concept: "概念",
  formula: "公式",
  principle: "原理",
  exercise: "练习",
  source: "来源",
  synthesis: "综合",
  query: "提问",
  unknown: "其他",
}

export const EDGE_LABELS: Record<string, string> = {
  prerequisite: "前置知识",
  derives: "推导",
  applies_to: "应用",
  teaches: "教学",
  scaffolds: "脚手架",
  related: "相关",
  direct: "直接引用",
  source: "同一来源",
}

export const COMMUNITY_COLORS = [
  "#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6",
  "#ec4899", "#06b6d4", "#84cc16", "#f97316", "#6366f1",
  "#14b8a6", "#a855f7",
]

export const BLOOM_LABELS: Record<string, string> = {
  remember: "记忆",
  understand: "理解",
  apply: "应用",
  analyze: "分析",
  evaluate: "评价",
  create: "创造",
}

export const DEFAULT_HIDDEN_TYPES = ["source", "unknown"]

export type ColorMode = "type" | "community"
