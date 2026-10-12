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
  concept: "Concept",
  formula: "Formula",
  principle: "Principle",
  source: "Source",
  synthesis: "Comprehensive",
  query: "Ask",
  mechanism: "Mechanism",
  property: "Performance",
  material: "Materials",
  composition: "Component",
  structure: "Organization",
  processing: "Process",
  instrument: "Representation",
  algorithm: "Algorithm",
  descriptor: "Descriptor",
  dataset: "Dataset",
  failure_mode: "Failure Modes",
  case: "Case",
  safety_rule: "Safety Rules",
  unknown: "Other",
}

export const EDGE_LABELS: Record<string, string> = {
  prerequisite: "Prerequisite Knowledge",
  derives: "Derivation",
  applies_to: "Apply",
  teaches: "Teaching",
  scaffolds: "Scaffold",
  related: "Related",
  direct: "Direct Citation",
  source: "Same Source",
  has_composition: "Has Component",
  composition_to_structure: "Composition Determines Structure",
  processed_by: "Process Applied",
  results_in_structure: "Form Organization",
  determines_property: "Determine Performance",
  explained_by: "Explained by mechanism",
  measured_by: "Measurement Methods",
  characterized_by: "Representation Features",
  modeled_by: "Modeling Methods",
  predicted_by: "Prediction Methods",
  uses_descriptor: "Use descriptor",
  leads_to_failure: "Causes Failure",
  diagnosed_by: "Diagnostic Methods",
  prevented_by: "Prevention Methods",
  safety_constraint_of: "Safety Constraints",
  supports_course: "Supporting Courses",
  // 本体知识单元关系(Stage 1b 抽取,origin=ontology;中文标签与 RELATION_SPECS 一致)
  isA: "属于",
  partOf: "部分于",
  prerequisiteOf: "先修于",
  explains: "解释",
  appliesTo: "适用于",
  exemplifies: "例证",
  supports: "支持",
  challenges: "质疑",
  operationalizedBy: "操作化为",
  usesVariable: "使用变量",
  formalizes: "形式化表达",
  derivedFrom: "推导自",
  providesInputTo: "提供输入",
  calculates: "计算得到",
}

/** 边类型 -> 颜色。每种关系一个色相;未列出的回退灰色。
 *  过滤面板的边类型复选框带同色色点,兼作图例。 */
export const EDGE_COLORS: Record<string, string> = {
  // 启发式边
  prerequisite: "#2563eb",
  teaches: "#64748b",
  related: "#94a3b8",
  direct: "#94a3b8",
  // 本体知识单元关系(Stage 1b,与 EDGE_LABELS 的键一一对应)
  isA: "#7c3aed",
  partOf: "#db2777",
  prerequisiteOf: "#0891b2",
  explains: "#d97706",
  appliesTo: "#65a30d",
  exemplifies: "#059669",
  supports: "#16a34a",
  challenges: "#dc2626",
  operationalizedBy: "#9333ea",
  usesVariable: "#ca8a04",
  formalizes: "#4f46e5",
  derivedFrom: "#c026d3",
  providesInputTo: "#ea580c",
  calculates: "#0d9488",
}

/** 默认隐藏的边类型(弱关联噪声;用户在过滤面板勾选显示)。 */
export const DEFAULT_HIDDEN_EDGE_TYPES = ["related"]

export const COMMUNITY_COLORS = [
  "#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6",
  "#ec4899", "#06b6d4", "#84cc16", "#f97316", "#6366f1",
  "#14b8a6", "#a855f7",
]

export const BLOOM_LABELS: Record<string, string> = {
  remember: "Memory",
  understand: "Understood",
  apply: "Apply",
  analyze: "Analyze",
  evaluate: "Evaluate",
  create: "Create",
}

export const DEFAULT_HIDDEN_TYPES = ["source", "unknown"]

export type ColorMode = "type" | "community"
