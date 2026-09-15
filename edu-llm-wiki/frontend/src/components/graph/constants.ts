// Static colour & label tables shared by the graph canvas and the
// filter/legend panels. Keep the keys in sync with backend node_type values.

export const TYPE_COLORS: Record<string, string> = {
  concept: "#3b82f6",
  formula: "#8b5cf6",
  principle: "#f59e0b",
  source: "#6b7280",
  synthesis: "#ec4899",
  query: "#06b6d4",
}

export const TYPE_LABELS: Record<string, string> = {
  concept: "概念",
  formula: "公式",
  principle: "原理",
  source: "来源",
  synthesis: "综合",
  query: "提问",
  mechanism: "机制",
  property: "性能",
  material: "材料",
  composition: "成分",
  structure: "组织",
  processing: "工艺",
  instrument: "表征",
  algorithm: "算法",
  descriptor: "描述符",
  dataset: "数据集",
  failure_mode: "失效模式",
  case: "案例",
  safety_rule: "安全规则",
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
  has_composition: "具有成分",
  composition_to_structure: "成分决定组织",
  processed_by: "经过工艺",
  results_in_structure: "形成组织",
  determines_property: "决定性能",
  explained_by: "由机制解释",
  measured_by: "测量方法",
  characterized_by: "表征特征",
  modeled_by: "建模方法",
  predicted_by: "预测方法",
  uses_descriptor: "使用描述符",
  leads_to_failure: "导致失效",
  diagnosed_by: "诊断方法",
  prevented_by: "预防方法",
  safety_constraint_of: "安全约束",
  supports_course: "支撑课程",
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
