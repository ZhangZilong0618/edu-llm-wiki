/**
 * Single source of truth for wiki page type metadata.
 *
 * 12 page types grouped by generation stage (A: import-time basics,
 * B: optional application, C: integration / evaluation). Adding a type
 * or moving it between groups means a single edit here, and consumers
 * (knowledge-tree, preview-panel, ingest engine) pick it up.
 */

export type ResearchAction = {
  id: string
  label: string
  description: string
}

import {
  Award,
  BookOpen,
  ClipboardList,
  Compass,
  FileText,
  FlaskConical,
  type LucideIcon,
  GitBranch,
  HelpCircle,
  Lightbulb,
  ListChecks,
  Network,
  Package,
  Scale,
  Sigma,
  Target,
  Workflow,
} from "lucide-react"

export type PageType =
  // Stage A — basics, generated on import
  | "source"
  | "concept"
  | "principle"
  | "formula"
  | "procedure"
  // Stage B — application pages, generated on demand
  | "example"
  | "misconception"
  // Stage C — integration / evaluation, generated when prerequisites are met
  | "synthesis"
  | "learning_path"
  | "learning_objective"
  | "rubric"
  // Internal
  | "archived"
  | "unknown"

export type GenerationStage = "A" | "B" | "C" | null

export const STAGE_LABELS: Record<Exclude<GenerationStage, null>, string> = {
  A: "Basics page",
  B: "Application page",
  C: "Integration/Evaluation Page",
}

export const PAGE_TYPE_ORDER: PageType[] = [
  "concept",
  "principle",
  "formula",
  "procedure",
  "example",
  "misconception",
  "synthesis",
  "learning_path",
  "learning_objective",
  "rubric",
  "source",
  "archived",
  "unknown",
]

export type PageTypeEntry = {
  /** Lucide icon for tree rows and badges. */
  Icon: LucideIcon
  /** Hex color (for non-Tailwind contexts like graph canvas). */
  hex: string
  /** Tailwind text color class. */
  twColor: string
  /** Tailwind background color class. */
  twBg: string
  /** Display label (Chinese). */
  label: string
  /** Short label (English) for compact contexts. */
  shortLabel: string
  /** When this page type is generated. */
  stage: GenerationStage
}

export const PAGE_TYPE_CONFIG: Record<PageType, PageTypeEntry> = {
  source: {
    Icon: FileText,
    hex: "#6b7280",
    twColor: "text-gray-500",
    twBg: "bg-gray-50 dark:bg-gray-950/30",
    label: "Source",
    shortLabel: "Source",
    stage: "A",
  },
  concept: {
    Icon: Sigma,
    hex: "#3b82f6",
    twColor: "text-blue-600",
    twBg: "bg-blue-50 dark:bg-blue-950/30",
    label: "Concept",
    shortLabel: "Concept",
    stage: "A",
  },
  principle: {
    Icon: Scale,
    hex: "#f59e0b",
    twColor: "text-amber-600",
    twBg: "bg-amber-50 dark:bg-amber-950/30",
    label: "Principle",
    shortLabel: "Principle",
    stage: "A",
  },
  formula: {
    Icon: FlaskConical,
    hex: "#8b5cf6",
    twColor: "text-violet-600",
    twBg: "bg-violet-50 dark:bg-violet-950/30",
    label: "Formula",
    shortLabel: "Formula",
    stage: "A",
  },
  procedure: {
    Icon: Workflow,
    hex: "#0ea5e9",
    twColor: "text-sky-600",
    twBg: "bg-sky-50 dark:bg-sky-950/30",
    label: "Method",
    shortLabel: "Procedure",
    stage: "A",
  },
  example: {
    Icon: Lightbulb,
    hex: "#10b981",
    twColor: "text-emerald-600",
    twBg: "bg-emerald-50 dark:bg-emerald-950/30",
    label: "Example",
    shortLabel: "Example",
    stage: "B",
  },
  misconception: {
    Icon: HelpCircle,
    hex: "#ef4444",
    twColor: "text-red-600",
    twBg: "bg-red-50 dark:bg-red-950/30",
    label: "Common Mistakes",
    shortLabel: "Misconception",
    stage: "B",
  },
  synthesis: {
    Icon: Network,
    hex: "#ec4899",
    twColor: "text-pink-600",
    twBg: "bg-pink-50 dark:bg-pink-950/30",
    label: "Comprehensive",
    shortLabel: "Synthesis",
    stage: "C",
  },
  learning_path: {
    Icon: GitBranch,
    hex: "#14b8a6",
    twColor: "text-teal-600",
    twBg: "bg-teal-50 dark:bg-teal-950/30",
    label: "Learning Path",
    shortLabel: "Path",
    stage: "C",
  },
  learning_objective: {
    Icon: Target,
    hex: "#a855f7",
    twColor: "text-purple-600",
    twBg: "bg-purple-50 dark:bg-purple-950/30",
    label: "Learning Objectives",
    shortLabel: "Objective",
    stage: "C",
  },
  rubric: {
    Icon: ClipboardList,
    hex: "#f97316",
    twColor: "text-orange-600",
    twBg: "bg-orange-50 dark:bg-orange-950/30",
    label: "Rubric",
    shortLabel: "Rubric",
    stage: "C",
  },
  archived: {
    Icon: Package,
    hex: "#9ca3af",
    twColor: "text-gray-400",
    twBg: "bg-gray-50 dark:bg-gray-950/20",
    label: "Archived",
    shortLabel: "Archived",
    stage: null,
  },
  unknown: {
    Icon: BookOpen,
    hex: "#9ca3af",
    twColor: "text-gray-400",
    twBg: "bg-gray-50 dark:bg-gray-950/20",
    label: "Other",
    shortLabel: "Other",
    stage: null,
  },
}

// ---- Research actions (consumed by preview-panel's ResearchPanel) --------

export const COMMON_RESEARCH_ACTIONS: ResearchAction[] = [
  { id: "explain", label: "In-Depth Explanation", description: "Explain it more clearly with examples and intuition." },
  { id: "prerequisites", label: "Fill in prerequisites", description: "List what you need to learn first to understand the current page." },
  { id: "related", label: "Related Knowledge", description: "Map its relationships with other pages in the wiki." },
  { id: "practice", label: "Generate Exercises", description: "Generate practice questions around the current page." },
  { id: "completeness", label: "Check completeness", description: "Point out which teaching elements are missing from the current page." },
  { id: "custom", label: "Custom", description: "Deep-dive into the current page using your own prompt." },
]

export const TYPE_RESEARCH_ACTIONS: Record<PageType, ResearchAction[]> = {
  source: [
    { id: "outline", label: "Extract Outline", description: "Organize the document structure, concepts, formulas, and exercises." },
    { id: "learning_path", label: "Learning Path", description: "Generate a learning path for this document in order." },
  ],
  concept: [
    { id: "examples", label: "Example/Counterexample", description: "Use materials science scenarios to illustrate concept boundaries." },
    { id: "boundaries", label: "Confusable Boundaries", description: "Explain the difference from similar concepts." },
  ],
  formula: [
    { id: "derive", label: "Derive Formula", description: "Outline the assumptions, derivation steps, and physical meaning." },
    { id: "variables", label: "Variables and units", description: "Explain each symbol, unit, and measurement method." },
    { id: "boundaries", label: "Applicable Boundaries", description: "Explain when it works and when it fails." },
  ],
  principle: [
    { id: "boundaries", label: "Applicable Boundaries", description: "Organize the conditions, failure cases, and approximation assumptions." },
    { id: "examples", label: "Material Cases", description: "Corresponds to real or instructional material phenomena." },
  ],
  procedure: [
    { id: "checklist", label: "Fill in checklist", description: "Make the key checkpoints in the process more actionable." },
    { id: "pitfalls", label: "Common pitfalls", description: "Outline the most common mistakes beginners make in this process." },
  ],
  example: [
    { id: "variation", label: "Variation", description: "Generate variants of the current example with the same structure but different parameters." },
    { id: "walkthrough", label: "Step-by-Step Explanation", description: "Break the example solution into finer sub-steps." },
  ],
  misconception: [
    { id: "diagnose", label: "Diagnostic question", description: "Generate short questions that distinguish correct from incorrect understanding." },
  ],
  synthesis: [
    { id: "examples", label: "Add Evidence", description: "Add examples, evidence, and contrasting perspectives." },
  ],
  learning_path: [
    { id: "outline", label: "Extract Outline", description: "Turn the current guide into actionable learning steps." },
  ],
  learning_objective: [
    { id: "evidence", label: "Evidence of Achievement", description: "Add observable criteria for each objective." },
  ],
  rubric: [
    { id: "calibrate", label: "Calibrate", description: "Use the example to give each level's descriptors more specific boundaries." },
  ],
  archived: [],
  unknown: [],
}

/** Group page types by generation stage for tree/filter UIs. */
export const STAGE_GROUPS: { stage: GenerationStage; types: PageType[] }[] = [
  { stage: "A", types: ["source", "concept", "principle", "formula", "procedure"] },
  { stage: "B", types: ["example", "misconception"] },
  { stage: "C", types: ["synthesis", "learning_path", "learning_objective", "rubric"] },
]

// ---- Badge component (single chip rendering for the 12 page types) ----

import type { ComponentType } from "react"

export function PageTypeBadge({
  pageType,
  size = "sm",
  className = "",
}: {
  pageType: string
  size?: "sm" | "xs"
  className?: string
}) {
  const entry = PAGE_TYPE_CONFIG[pageType as PageType] ?? PAGE_TYPE_CONFIG.unknown
  const sizeCls = size === "xs" ? "text-[9px] px-1.5 py-0.5" : "text-[10px] px-2 py-0.5"
  const Icon = entry.Icon
  return (
    <span
      className={`inline-flex items-center gap-1 font-medium rounded-full ${entry.twBg} ${entry.twColor} ${sizeCls} ${className}`}
    >
      <Icon size={size === "xs" ? 9 : 11} />
      {entry.label}
    </span>
  )
}
