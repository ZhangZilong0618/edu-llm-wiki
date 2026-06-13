/**
 * Page badges for the knowledge tree.
 *
 * Renders small metadata chips at the end of each tree row so learners can
 * see, at a glance, how hard a page is, what it depends on, what traps
 * it warns about, and when it was last reviewed.
 *
 * All inputs are tolerant of the v1 shape (where these fields don't yet
 * exist on a page) and render a muted "empty" state instead of crashing.
 */
import type { ReactNode } from "react"

type PageShape = {
  difficulty?: number | null
  prerequisites?: string[] | null
  common_misconceptions?: string[] | null
  last_reviewed?: string | null
}

// kept for any future callers that want the object form
export type { PageShape }

const DOT_FILLED = "#3b82f6"
const DOT_EMPTY = "var(--muted-foreground)"

function difficultyDots(level: number | null | undefined, max: number = 5): ReactNode {
  const n = typeof level === "number" ? Math.max(0, Math.min(max, level)) : 0
  const dots: ReactNode[] = []
  for (let i = 0; i < max; i++) {
    dots.push(
      <span
        key={i}
        style={{
          display: "inline-block",
          width: 4,
          height: 4,
          marginRight: 1.5,
          borderRadius: "50%",
          background: i < n ? DOT_FILLED : DOT_EMPTY,
          opacity: i < n ? 1 : 0.3,
        }}
      />
    )
  }
  return <span style={{ display: "inline-flex", alignItems: "center" }}>{dots}</span>
}

function daysSince(iso: string | null | undefined): number | null {
  if (!iso) return null
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return null
  const ms = Date.now() - t
  return Math.max(0, Math.floor(ms / 86_400_000))
}

export function PageBadges({
  difficulty,
  prerequisiteCount,
  misconceptionCount,
  lastReviewed,
}: {
  difficulty?: number | null
  prerequisiteCount?: number
  misconceptionCount?: number
  lastReviewed?: string | null
}) {
  const d = difficulty ?? null
  const prereqN = prerequisiteCount ?? 0
  const misconN = misconceptionCount ?? 0
  const days = daysSince(lastReviewed)

  const items: Array<{ key: string; el: ReactNode; title: string }> = []

  if (d != null) {
    items.push({
      key: "diff",
      el: difficultyDots(d),
      title: `难度 ${d}/5`,
    })
  }

  if (prereqN > 0) {
    items.push({
      key: "prereq",
      el: <span style={{ fontSize: 9, fontWeight: 600 }}>↑{prereqN}</span>,
      title: `${prereqN} 个前置知识`,
    })
  }

  if (misconN > 0) {
    items.push({
      key: "miscon",
      el: <span style={{ fontSize: 9, fontWeight: 600 }}>!{misconN}</span>,
      title: `${misconN} 个常见误区`,
    })
  }

  if (days != null) {
    items.push({
      key: "review",
      el: (
        <span style={{ fontSize: 9, fontVariantNumeric: "tabular-nums" }}>
          {days === 0 ? "今日" : days < 30 ? `${days}d` : `${Math.floor(days / 30)}mo`}
        </span>
      ),
      title: days === 0 ? "今日复习过" : `${days} 天前复习`,
    })
  }

  if (items.length === 0) return null

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        marginLeft: 6,
        verticalAlign: "middle",
      }}
    >
      {items.map((it) => (
        <span
          key={it.key}
          title={it.title}
          style={{
            display: "inline-flex",
            alignItems: "center",
            padding: "0 4px",
            height: 14,
            borderRadius: 3,
            color: "var(--muted-foreground)",
            background: "transparent",
          }}
        >
          {it.el}
        </span>
      ))}
    </span>
  )
}
