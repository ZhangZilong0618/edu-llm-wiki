/**
 * Bottom-of-page frontmatter cards for structured v2 fields.
 *
 * Per docs/wiki-redesign.md §4: prerequisites / related / common_misconceptions
 * / last_reviewed render as small cards beneath the markdown body. Each
 * section is independently optional — empty arrays / null dates collapse to
 * nothing.
 */
import type { WikiPage } from "@/types/wiki"
import { displayWikiTitle } from "@/lib/wiki-title"

function pathLabel(path: string) {
  return path.split("/").pop()?.replace(/\.md$/, "") ?? path
}

type SectionProps = {
  title: string
  items: string[]
  emptyHint?: string
}

function ListSection({ title, items, emptyHint }: SectionProps) {
  if (items.length === 0) return null
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--muted)]/40 p-3">
      <div className="text-[10px] uppercase tracking-wider text-[var(--muted-foreground)]">{title}</div>
      <ul className="mt-1.5 space-y-1">
        {items.map((item) => (
          <li key={item} className="text-xs text-[var(--foreground)]">
            {item}
          </li>
        ))}
      </ul>
      {emptyHint && items.length === 0 ? <div className="mt-1 text-[10px] text-[var(--muted-foreground)]">{emptyHint}</div> : null}
    </div>
  )
}

function daysSince(iso: string | null | undefined): number | null {
  if (!iso) return null
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return null
  const ms = Date.now() - t
  return Math.max(0, Math.floor(ms / 86_400_000))
}

export function FrontmatterCards({ page }: { page: WikiPage }) {
  const prereqs = page.prerequisites ?? []
  const related = page.related ?? []
  const misconceptions = page.common_misconceptions ?? []
  const workedExampleRefs = page.worked_example_ref ?? []
  const days = daysSince(page.last_reviewed)

  const hasAnything =
    prereqs.length > 0 ||
    related.length > 0 ||
    misconceptions.length > 0 ||
    workedExampleRefs.length > 0 ||
    days != null
  if (!hasAnything) return null

  return (
    <div className="mt-6 grid gap-3 sm:grid-cols-2">
      <ListSection title="前置知识 / Prerequisites" items={prereqs.map(pathLabel)} />
      <ListSection title="相关 / Related" items={related.map(pathLabel)} />
      <ListSection
        title="常见误区 / Common misconceptions"
        items={misconceptions}
      />
      {workedExampleRefs.length > 0 && (
        <ListSection
          title="典型例题 / Worked examples"
          items={workedExampleRefs.map(pathLabel)}
        />
      )}
      {days != null && (
        <div className="rounded-md border border-[var(--border)] bg-[var(--muted)]/40 p-3 sm:col-span-2">
          <div className="text-[10px] uppercase tracking-wider text-[var(--muted-foreground)]">
            复习 / Last reviewed
          </div>
          <div className="mt-1 text-xs text-[var(--foreground)]">
            {days === 0 ? "今日复习过" : `${days} 天前复习`}
          </div>
        </div>
      )}
    </div>
  )
}
