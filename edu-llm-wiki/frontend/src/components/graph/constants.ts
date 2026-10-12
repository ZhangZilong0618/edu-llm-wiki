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
}

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
