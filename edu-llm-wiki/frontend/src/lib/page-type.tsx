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
  A: "基础页",
  B: "应用页",
  C: "整合/评价页",
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
    label: "来源",
    shortLabel: "Source",
    stage: "A",
  },
  concept: {
    Icon: Sigma,
    hex: "#3b82f6",
    twColor: "text-blue-600",
    twBg: "bg-blue-50 dark:bg-blue-950/30",
    label: "概念",
    shortLabel: "Concept",
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
  formula: {
    Icon: FlaskConical,
    hex: "#8b5cf6",
    twColor: "text-violet-600",
    twBg: "bg-violet-50 dark:bg-violet-950/30",
    label: "公式",
    shortLabel: "Formula",
    stage: "A",
  },
  procedure: {
    Icon: Workflow,
    hex: "#0ea5e9",
    twColor: "text-sky-600",
    twBg: "bg-sky-50 dark:bg-sky-950/30",
    label: "方法",
    shortLabel: "Procedure",
    stage: "A",
  },
  example: {
    Icon: Lightbulb,
    hex: "#10b981",
    twColor: "text-emerald-600",
    twBg: "bg-emerald-50 dark:bg-emerald-950/30",
    label: "例题",
    shortLabel: "Example",
    stage: "B",
  },
  misconception: {
    Icon: HelpCircle,
    hex: "#ef4444",
    twColor: "text-red-600",
    twBg: "bg-red-50 dark:bg-red-950/30",
    label: "易错点",
    shortLabel: "Misconception",
    stage: "B",
  },
  synthesis: {
    Icon: Network,
    hex: "#ec4899",
    twColor: "text-pink-600",
    twBg: "bg-pink-50 dark:bg-pink-950/30",
    label: "综合",
    shortLabel: "Synthesis",
    stage: "C",
  },
  learning_path: {
    Icon: GitBranch,
    hex: "#14b8a6",
    twColor: "text-teal-600",
    twBg: "bg-teal-50 dark:bg-teal-950/30",
    label: "学习路径",
    shortLabel: "Path",
    stage: "C",
  },
  learning_objective: {
    Icon: Target,
    hex: "#a855f7",
    twColor: "text-purple-600",
    twBg: "bg-purple-50 dark:bg-purple-950/30",
    label: "学习目标",
    shortLabel: "Objective",
    stage: "C",
  },
  rubric: {
    Icon: ClipboardList,
    hex: "#f97316",
    twColor: "text-orange-600",
    twBg: "bg-orange-50 dark:bg-orange-950/30",
    label: "评价量规",
    shortLabel: "Rubric",
    stage: "C",
  },
  archived: {
    Icon: Package,
    hex: "#9ca3af",
    twColor: "text-gray-400",
    twBg: "bg-gray-50 dark:bg-gray-950/20",
    label: "已归档",
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
  { id: "explain", label: "深入解释", description: "换一种更清楚的讲法，补例子和直觉。" },
  { id: "prerequisites", label: "补前置知识", description: "列出看懂当前页需要先学什么。" },
  { id: "related", label: "关联知识", description: "梳理它和 wiki 里其他页面的关系。" },
  { id: "practice", label: "生成练习", description: "围绕当前页生成可训练的小题。" },
  { id: "completeness", label: "检查完整性", description: "指出当前页还缺哪些教学要素。" },
  { id: "custom", label: "自定义", description: "按你自己写的提示词深入研究当前页面。" },
]

export const TYPE_RESEARCH_ACTIONS: Record<PageType, ResearchAction[]> = {
  source: [
    { id: "outline", label: "提炼大纲", description: "整理文档结构、概念、公式和练习。" },
    { id: "learning_path", label: "学习路线", description: "按顺序生成这份文档的学习路线。" },
  ],
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
  procedure: [
    { id: "checklist", label: "补检查清单", description: "把流程中的关键检查点写得更可执行。" },
    { id: "pitfalls", label: "常见坑", description: "梳理新手在该流程中最常犯的错误。" },
  ],
  example: [
    { id: "variation", label: "变式", description: "对当前例题生成同结构不同参数的变式。" },
    { id: "walkthrough", label: "分步讲解", description: "把例题解答拆成更细的子步骤。" },
  ],
  misconception: [
    { id: "diagnose", label: "诊断题", description: "生成能区分错/对理解的小问题。" },
  ],
  synthesis: [
    { id: "examples", label: "补充证据", description: "补充例子、证据和对比视角。" },
  ],
  learning_path: [
    { id: "outline", label: "提炼大纲", description: "把当前指南整理成可执行的学习步骤。" },
  ],
  learning_objective: [
    { id: "evidence", label: "达成证据", description: "为每条目标补可观察的判断标准。" },
  ],
  rubric: [
    { id: "calibrate", label: "校准", description: "对照例题给各档描述更具体的边界。" },
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
