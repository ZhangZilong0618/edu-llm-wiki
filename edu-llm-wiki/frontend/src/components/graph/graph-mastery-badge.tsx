// Small chip showing a node's mastery level. Used in the node-detail panel
// and in the learning-path step rows so users can see at a glance what
// they've already mastered.

import { CircleDashed, BookOpen, Sparkles, BadgeCheck, Crown } from "lucide-react"

type Level = "new" | "exposed" | "learning" | "proficient" | "mastered"

const MASTERY_META: Record<Level, { label: string; cls: string; Icon: typeof CircleDashed }> = {
  new: { label: "未学习", cls: "inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] text-slate-500", Icon: CircleDashed },
  exposed: { label: "已浏览", cls: "inline-flex items-center gap-1 rounded-full border border-sky-200 bg-sky-50 px-1.5 py-0.5 text-[10px] text-sky-700", Icon: BookOpen },
  learning: { label: "学习中", cls: "inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700", Icon: Sparkles },
  proficient: { label: "已掌握", cls: "inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-700", Icon: BadgeCheck },
  mastered: { label: "精通", cls: "inline-flex items-center gap-1 rounded-full border border-violet-200 bg-violet-50 px-1.5 py-0.5 text-[10px] text-violet-700", Icon: Crown },
}

export function GraphMasteryBadge({ level }: { level: Level }) {
  const meta = MASTERY_META[level] ?? MASTERY_META.new
  const Icon = meta.Icon
  return (
    <span className={meta.cls}>
      <Icon size={11} />
      {meta.label}
    </span>
  )
}