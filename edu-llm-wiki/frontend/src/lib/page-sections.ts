/**
 * Helpers for pulling structured content out of `page.content` markdown bodies.
 *
 * The redesign §3.3 keeps the v2 design fields (statement / variables /
 * applicability / etc.) inside the body as `##` sections rather than promoting
 * them to frontmatter. Each per-type view therefore reaches into the body
 * with these helpers to render its type-specific card row.
 */

const WIKILINK_RE = /\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]/g

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

/**
 * Return the body slice under the first matching `## heading` (case-insensitive,
 * Chinese or English aliases). Returns `null` if no matching heading exists or
 * the slice is empty.
 */
export function extractSection(
  markdown: string,
  headings: string[],
): string | null {
  if (!markdown) return null
  const pattern = headings.map(escapeRegExp).join("|")
  const re = new RegExp(
    `^##\\s*(?:${pattern})\\s*\\n([\\s\\S]*?)(?=^##\\s+|\\s*$)`,
    "im",
  )
  const match = markdown.match(re)
  const slice = match?.[1]?.trim()
  return slice ? slice : null
}

/**
 * Extract all `[[wikilink]]` targets from a markdown body. Returns just the
 * path portion (no alias, no anchor).
 */
export function extractWikilinks(markdown: string): string[] {
  if (!markdown) return []
  const out: string[] = []
  const seen = new Set<string>()
  for (const m of markdown.matchAll(WIKILINK_RE)) {
    const path = m[1].trim()
    if (!path || seen.has(path)) continue
    seen.add(path)
    out.push(path)
  }
  return out
}

/**
 * Extract a single-line summary: the first non-empty paragraph of the body
 * that isn't a heading or wikilink list.
 */
export function firstParagraph(markdown: string): string | null {
  if (!markdown) return null
  const lines = markdown.split("\n")
  let buf: string[] = []
  for (const raw of lines) {
    const line = raw.trimEnd()
    if (!line.trim()) {
      if (buf.length) break
      continue
    }
    if (/^#{1,6}\s+/.test(line)) {
      if (buf.length) break
      continue
    }
    if (/^[-*+]\s+/.test(line) || /^>\s+/.test(line)) {
      if (buf.length) break
      continue
    }
    buf.push(line.trim())
  }
  const text = buf.join(" ").replace(/\s+/g, " ").trim()
  return text || null
}
