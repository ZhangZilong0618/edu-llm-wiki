import { useMemo, useState } from "react"
import { Markdown } from "@/components/markdown"
import type { WikiPage } from "@/types/wiki"
import { FrontmatterCards } from "./FrontmatterCards"
import { useAppStore } from "@/stores/app-store"

function basename(path: string): string {
  return path.split("/").pop() || path
}

export function BodyShell({
  page,
  tagClassName,
  children,
}: {
  page: WikiPage
  tagClassName?: string
  children?: React.ReactNode
}) {
  const currentProject = useAppStore((s) => s.currentProject)
  const [showUnverified, setShowUnverified] = useState(false)
  const unverified = page.unverified_refs ?? []
  const verified = page.source_refs?.filter((r) => r.verified) ?? []
  const allRefs = page.source_refs ?? []
  const hasRefs = allRefs.length > 0 || unverified.length > 0

  // Build a (file, page) → status lookup for the markdown renderer. Pages
  // without source_refs render the citation markers without any color
  // differentiation (status === undefined).
  const citationStatus = useMemo(() => {
    const all = [...(page.source_refs ?? []), ...unverified]
    if (!all.length) return undefined
    const map = new Map<string, "verified" | "unverified">()
    for (const r of all) {
      const key = `${r.file}#p=${r.page}`
      // If a (file,page) is referenced both verified AND unverified (rare
      // — happens when the LLM emits the same ref twice with different
      // text), keep the verified flag.
      const cur = map.get(key)
      if ("verified" in r && r.verified) {
        map.set(key, "verified")
      } else if (!cur) {
        map.set(key, "unverified")
      }
    }
    return (file: string, page: number) => map.get(`${file}#p=${page}`)
  }, [page.source_refs, unverified])

  // Quote lookup: only verified refs pass their quote to the popover so the
  // server can compute hit_offsets. Unverified refs intentionally pass
  // nothing — the popover still shows the page, but no span is highlighted.
  const citationQuoteLookup = useMemo(() => {
    const verified = page.source_refs?.filter((r) => r.verified) ?? []
    if (!verified.length) return undefined
    const map = new Map<string, string>()
    for (const r of verified) {
      const key = `${r.file}#p=${r.page}`
      if (!map.has(key) && r.quote) map.set(key, r.quote)
    }
    return (file: string, page: number) => map.get(`${file}#p=${page}`)
  }, [page.source_refs])

  return (
    <div>
      {page.tags.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1">
          {page.tags.map((t) => (
            <span
              key={t}
              className={
                tagClassName ??
                "rounded bg-[var(--muted)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]"
              }
            >
              #{t}
            </span>
          ))}
        </div>
      )}
      {children}
      <Markdown
        projectId={currentProject}
        enableCitations
        citationStatus={citationStatus}
        citationQuoteLookup={citationQuoteLookup}
        defaultSource={page.sources?.[0]}
      >
        {page.content || "*No content*"}
      </Markdown>
      <FrontmatterCards page={page} />

      {hasRefs && (
        <div className="mt-4 rounded-md border border-[var(--border)] bg-[var(--muted)]/50 p-2.5 text-[11px]">
          <div className="mb-1.5 font-medium text-[var(--foreground)]">
            引用溯源
            <span className="ml-2 text-[var(--muted-foreground)]">
              {verified.length > 0 && (
                <span className="mr-2 text-green-600">✓ {verified.length} 已验证</span>
              )}
              {unverified.length > 0 && (
                <span className="text-amber-600">⚠ {unverified.length} 未验证</span>
              )}
            </span>
          </div>
          {verified.length > 0 && (
            <ul className="space-y-1 text-[var(--muted-foreground)]">
              {verified.slice(0, 6).map((r, i) => (
                <li key={`v-${i}`} className="flex gap-2">
                  <span className="shrink-0 font-mono text-[10px] text-green-700">
                    ✓
                  </span>
                  <span className="shrink-0">
                    {basename(r.file)} · 第 {r.page} 页
                  </span>
                  <span className="truncate italic">「{r.quote}」</span>
                </li>
              ))}
              {verified.length > 6 && (
                <li className="text-[10px] text-[var(--muted-foreground)]">
                  还有 {verified.length - 6} 条已验证引用…
                </li>
              )}
            </ul>
          )}
          {unverified.length > 0 && (
            <div className="mt-2">
              <button
                type="button"
                onClick={() => setShowUnverified((v) => !v)}
                className="text-[10px] text-amber-700 underline hover:text-amber-800"
              >
                {showUnverified ? "收起" : "展开"}未验证引用 ({unverified.length})
              </button>
              {showUnverified && (
                <ul className="mt-1.5 space-y-1 text-[var(--muted-foreground)]">
                  {unverified.map((r, i) => (
                    <li key={`u-${i}`} className="flex gap-2">
                      <span className="shrink-0 font-mono text-[10px] text-amber-700">
                        ?
                      </span>
                      <span className="shrink-0">
                        {basename(r.file)} · 第 {r.page} 页
                      </span>
                      <span className="truncate italic">「{r.quote}」</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      {page.sources.length > 0 && (
        <div className="mt-2 text-[10px] text-[var(--muted-foreground)]">
          来源文件：{page.sources.map((s) => basename(s)).join(" · ")}
        </div>
      )}
    </div>
  )
}
