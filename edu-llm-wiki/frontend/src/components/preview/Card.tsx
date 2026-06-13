/**
 * Tiny visual primitive shared by all per-type views.
 *
 * Renders a small panel with an uppercased title in the muted foreground
 * color and body content beneath. Used to host the type-specific structured
 * content (definition card, formula card, applicability list, etc.) that
 * sits on top of the markdown body per docs/wiki-redesign.md §4.2.
 */
import type { ReactNode } from "react"

export function Card({
  title,
  accent,
  children,
  className = "",
}: {
  title: string
  /** Optional Tailwind text-color class (e.g. "text-blue-600") for the heading. */
  accent?: string
  children: ReactNode
  className?: string
}) {
  return (
    <div
      className={`rounded-md border border-[var(--border)] bg-[var(--muted)]/40 p-3 ${className}`}
    >
      <div
        className={`text-[10px] uppercase tracking-wider ${accent ?? "text-[var(--muted-foreground)]"}`}
      >
        {title}
      </div>
      <div className="mt-1.5 text-xs leading-relaxed text-[var(--foreground)]">
        {children}
      </div>
    </div>
  )
}

/** Render a markdown slice as small text. Used by section-based views. */
export function MarkdownSlice({ markdown }: { markdown: string }) {
  return <div className="whitespace-pre-wrap">{markdown}</div>
}

/** Render a list of strings as a bullet list with consistent spacing. */
export function Bullets({ items }: { items: string[] }) {
  if (items.length === 0) return null
  return (
    <ul className="space-y-1">
      {items.map((item, i) => (
        <li key={i} className="leading-relaxed">
          {item}
        </li>
      ))}
    </ul>
  )
}
