"use client"
// BKT p_known visualiser. Horizontal bar with state color.
import { CircleDashed, BookOpen, Sparkles, BadgeCheck, Crown } from "lucide-react"
const LEVELS = [
  { max: 0.2, label: "未接触", color: "bg-slate-400", icon: CircleDashed },
  { max: 0.5, label: "已接触过", color: "bg-blue-500", icon: BookOpen },
  { max: 0.7, label: "学习中", color: "bg-amber-500", icon: Sparkles },
  { max: 0.85, label: "基本掌握", color: "bg-emerald-500", icon: BadgeCheck },
  { max: 1.01, label: "精通", color: "bg-violet-500", icon: Crown },
] as const
export function PosteriorBar({ p_known }: { p_known: number }) {
  const pct = Math.max(0, Math.min(1, p_known))
  const lvl = LEVELS.find((l) => pct < l.max) || LEVELS[LEVELS.length - 1]
  const Icon = lvl.icon
  return (
    <div className="space-y-1">
      <div className="h-1.5 w-full rounded-full bg-slate-200">
        <div className={`h-1.5 rounded-full ${lvl.color} transition-all`} style={{ width: `${pct * 100}%` }} />
      </div>
      <div className="flex items-center gap-1 text-[10px] text-[var(--muted-foreground)]">
        <Icon size={10} /> {lvl.label} · {(pct * 100).toFixed(0)}%
      </div>
    </div>
  )
}
