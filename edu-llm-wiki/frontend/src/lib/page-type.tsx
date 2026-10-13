/**
 * Single source of truth for wiki page type metadata.
 *
 * 4 knowledge-unit page types (concept / fact / formula / principle),
 * aligned with the v2 ontology's KnowledgeUnit subclasses, plus internal
 * bookkeeping states (archived / unknown). Adding a type means a single
 * edit here, and consumers (knowledge-tree, preview-panel, ingest engine)
 * pick it up.
 */

export type ResearchAction = {
  id: string
  label: string
  description: string
}

import {
  BookOpen,
  FlaskConical,
  type LucideIcon,
  Hash,
  Package,
  Scale,
  Sigma,
} from "lucide-react"

export type PageType =
  // Knowledge units — generated on import
  | "concept"
  | "fact"
  | "formula"
  | "principle"
  // Internal
  | "archived"
  | "unknown"

export type GenerationStage = "A" | null

export const STAGE_LABELS: Record<Exclude<GenerationStage, null>, string> = {
  A: "Basics page",
}

export const PAGE_TYPE_ORDER: PageType[] = [
  "concept",
  "fact",
  "formula",
  "principle",
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
  /** Display label. */
  label: string
  /** Short label (English) for compact contexts. */
  shortLabel: string
  /** When this page type is generated. */
  stage: GenerationStage
}

export const PAGE_TYPE_CONFIG: Record<PageType, PageTypeEntry> = {
  concept: {
    Icon: Sigma,
    hex: "#3b82f6",
    twColor: "text-blue-600",
    twBg: "bg-blue-50 dark:bg-blue-950/30",
    label: "概念",
    shortLabel: "Concept",
    stage: "A",
  },
  fact: {
    Icon: Hash,
    hex: "#10b981",
    twColor: "text-emerald-600",
    twBg: "bg-emerald-50 dark:bg-emerald-950/30",
    label: "事实",
    shortLabel: "Fact",
    stage: "A",
  },
  formula: {
    Icon: FlaskConical,
    hex: "#8b5cf6",
    twColor: "text-violet-600",
    twBg: "bg-violet-50 dark:bg-violet-950/30",
    label: "公式",
    shortLabel: "Formula",
    stage: "A",
  },
  principle: {
    Icon: Scale,
    hex: "#f59e0b",
    twColor: "text-amber-600",
    twBg: "bg-amber-50 dark:bg-amber-950/30",
    label: "原理",
    shortLabel: "Principle",
    stage: "A",
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
    label: "其他",
    shortLabel: "Other",
    stage: null,
  },
}

// ---- Research actions (consumed by preview-panel's ResearchPanel) --------

export const COMMON_RESEARCH_ACTIONS: ResearchAction[] = [
  { id: "explain", label: "深入解释", description: "Explain it more clearly with examples and intuition." },
  { id: "prerequisites", label: "补齐前置", description: "List what you need to learn first to understand the current page." },
  { id: "related", label: "相关知识", description: "Map its relationships with other pages in the wiki." },
  { id: "completeness", label: "检查完整性", description: "Point out which teaching elements are missing from the current page." },
  { id: "custom", label: "自定义", description: "Deep-dive into the current page using your own prompt." },
]

export const TYPE_RESEARCH_ACTIONS: Record<PageType, ResearchAction[]> = {
  concept: [
    { id: "examples", label: "正例/反例", description: "Use concrete scenarios to illustrate concept boundaries." },
    { id: "boundaries", label: "易混边界", description: "Explain the difference from similar concepts." },
  ],
  fact: [],
  formula: [
    { id: "derive", label: "推导公式", description: "Outline the assumptions, derivation steps, and physical meaning." },
    { id: "variables", label: "变量与单位", description: "Explain each symbol, unit, and measurement method." },
    { id: "boundaries", label: "适用边界", description: "Explain when it works and when it fails." },
  ],
  principle: [
    { id: "boundaries", label: "适用边界", description: "Organize the conditions, failure cases, and approximation assumptions." },
    { id: "examples", label: "实例", description: "Corresponds to real or instructional phenomena." },
  ],
  archived: [],
  unknown: [],
}

/** Group page types by generation stage for tree/filter UIs. */
export const STAGE_GROUPS: { stage: GenerationStage; types: PageType[] }[] = [
  { stage: "A", types: ["concept", "fact", "formula", "principle"] },
]

// ---- Badge component (single chip rendering for the page types) ----

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
