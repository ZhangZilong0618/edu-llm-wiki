/**
 * Single source of truth for wiki page type metadata.
 *
 * Three call sites used to keep their own copies of this — knowledge-tree,
 * learn-view, and preview-panel — so renaming a type or adding a new one
 * meant three edits that could drift. Per docs/wiki-redesign.md §4.3,
 * everything type-shaped lives here.
 */

export type ResearchAction = {
  id: string
  label: string
  description: string
}

import {
  BookOpen,
  Compass,
  FileText,
  FlaskConical,
  HelpCircle,
  type LucideIcon,
  Network,
  Package,
  Scale,
  Sigma,
} from "lucide-react"

export type PageType =
  | "concept"
  | "formula"
  | "principle"
  | "synthesis"
  | "inquiry"
  | "guide"
  | "source"
  | "archived"
  | "unknown"

export const PAGE_TYPE_ORDER: PageType[] = [
  "concept",
  "formula",
  "principle",
  "inquiry",
  "guide",
  "synthesis",
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
}

export const PAGE_TYPE_CONFIG: Record<PageType, PageTypeEntry> = {
  concept: {
    Icon: Sigma,
    hex: "#3b82f6",
    twColor: "text-blue-600",
    twBg: "bg-blue-50 dark:bg-blue-950/30",
    label: "概念",
    shortLabel: "Concept",
  },
  formula: {
    Icon: FlaskConical,
    hex: "#8b5cf6",
    twColor: "text-violet-600",
    twBg: "bg-violet-50 dark:bg-violet-950/30",
    label: "公式",
    shortLabel: "Formula",
  },
  principle: {
    Icon: Scale,
    hex: "#f59e0b",
    twColor: "text-amber-600",
    twBg: "bg-amber-50 dark:bg-amber-950/30",
    label: "原理",
    shortLabel: "Principle",
  },
  synthesis: {
    Icon: Network,
    hex: "#ec4899",
    twColor: "text-pink-600",
    twBg: "bg-pink-50 dark:bg-pink-950/30",
    label: "综合",
    shortLabel: "Synthesis",
  },
  inquiry: {
    Icon: HelpCircle,
    hex: "#06b6d4",
    twColor: "text-cyan-600",
    twBg: "bg-cyan-50 dark:bg-cyan-950/30",
    label: "问答",
    shortLabel: "Inquiry",
  },
  guide: {
    Icon: Compass,
    hex: "#64748b",
    twColor: "text-slate-600",
    twBg: "bg-slate-50 dark:bg-slate-950/30",
    label: "指引",
    shortLabel: "Guide",
  },
  source: {
    Icon: FileText,
    hex: "#6b7280",
    twColor: "text-gray-500",
    twBg: "bg-gray-50 dark:bg-gray-950/30",
    label: "来源",
    shortLabel: "Source",
  },
  archived: {
    Icon: Package,
    hex: "#9ca3af",
    twColor: "text-gray-400",
    twBg: "bg-gray-50 dark:bg-gray-950/20",
    label: "已归档",
    shortLabel: "Archived",
  },
  unknown: {
    Icon: BookOpen,
    hex: "#9ca3af",
    twColor: "text-gray-400",
    twBg: "bg-gray-50 dark:bg-gray-950/20",
    label: "其他",
    shortLabel: "Other",
  },
}

// ---- Research actions (consumed by preview-panel's ResearchPanel) --------

export const COMMON_RESEARCH_ACTIONS: ResearchAction[] = [
  { id: "explain", label: "深入解释", description: "换一种更清楚的讲法，补例子和直觉。" },
  { id: "prerequisites", label: "补前置知识", description: "列出看懂当前页需要先学什么。" },
  { id: "related", label: "关联知识", description: "梳理它和 wiki 里其他页面的关系。" },
  { id: "practice", label: "生成练习", description: "围绕当前页生成可训练的小题。" },
  { id: "completeness", label: "检查完整性", description: "指出当前页还缺哪些教学要素。" },
  { id: "custom", label: "自定义", description: "按你自己写的提示词深入研究当前页面。" },
]

export const TYPE_RESEARCH_ACTIONS: Record<PageType, ResearchAction[]> = {
  concept: [
    { id: "examples", label: "例子/反例", description: "用材料科学场景说明概念边界。" },
    { id: "boundaries", label: "易混边界", description: "说明与相近概念的区别。" },
  ],
  formula: [
    { id: "derive", label: "推导公式", description: "梳理假设、推导步骤和物理意义。" },
    { id: "variables", label: "变量与单位", description: "逐项解释符号、单位和测量方式。" },
    { id: "boundaries", label: "适用边界", description: "说明什么时候能用，什么时候会失效。" },
  ],
  principle: [
    { id: "boundaries", label: "适用边界", description: "整理条件、失效情况和近似假设。" },
    { id: "examples", label: "材料案例", description: "对应真实或教学材料现象。" },
  ],
  synthesis: [
    { id: "examples", label: "补充证据", description: "补充例子、证据和对比视角。" },
  ],
  inquiry: [
    { id: "perspectives", label: "多视角", description: "列出不同立场对这个问题的回答。" },
  ],
  guide: [
    { id: "outline", label: "提炼大纲", description: "把当前指南整理成可执行的学习步骤。" },
  ],
  source: [
    { id: "outline", label: "提炼大纲", description: "整理文档结构、概念、公式和练习。" },
    { id: "learning_path", label: "学习路线", description: "按顺序生成这份文档的学习路线。" },
  ],
  archived: [],
  unknown: [],
}
