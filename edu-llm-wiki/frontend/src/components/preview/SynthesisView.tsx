/**
 * Synthesis page view.
 *
 * Per docs/wiki-redesign.md §4.2 the top of a synthesis page shows a
 * "thesis" (one-line summary) and an "evidence" list of cross-page
 * references. We surface the first paragraph of the body as the thesis
 * and the `[[wikilinks]]` set as clickable chips.
 */
import { BodyShell } from "./BodyShell"
import { Card, Bullets } from "./Card"
import { extractWikilinks, firstParagraph } from "@/lib/page-sections"
import { useAppStore } from "@/stores/app-store"
import { displayWikiTitle, pathLabel } from "@/lib/wiki-title"
import type { WikiPage } from "@/types/wiki"

export function SynthesisView({ page }: { page: WikiPage }) {
  const thesis = firstParagraph(page.content)
  const evidence = extractWikilinks(page.content)
  const wikiPages = useAppStore((s) => s.wikiPages)
  const setActiveView = useAppStore((s) => s.setActiveView)
  const selectPage = useAppStore((s) => s.selectPage)

  const evidenceLookup = new Map(wikiPages.map((p) => [p.path.replace(/\.md$/, ""), p]))

  return (
    <BodyShell
      page={page}
      tagClassName="rounded bg-pink-50 px-1.5 py-0.5 text-[10px] text-pink-600 dark:bg-pink-950/30"
    >
      {thesis && (
        <div className="mb-3">
          <Card title="综合论点 / Thesis" accent="text-pink-600">
            <p className="text-[13px] italic leading-relaxed">{thesis}</p>
          </Card>
        </div>
      )}
      {evidence.length > 0 && (
        <div className="mb-3">
          <Card title="证据 / Evidence" accent="text-pink-600">
            <div className="flex flex-wrap gap-1.5">
              {evidence.map((path) => {
                const p = evidenceLookup.get(path)
                const label = p ? displayWikiTitle(p) : pathLabel(path)
                return (
                  <button
                    key={path}
                    onClick={() => {
                      if (p) {
                        selectPage(p.path)
                        setActiveView("wiki")
                      } else {
                        selectPage(path.endsWith(".md") ? path : `${path}.md`)
                      }
                    }}
                    className="inline-flex items-center rounded border border-pink-200 bg-pink-50 px-2 py-0.5 text-[11px] text-pink-700 hover:bg-pink-100 dark:border-pink-900 dark:bg-pink-950/30 dark:text-pink-300"
                  >
                    {label}
                  </button>
                )
              })}
            </div>
          </Card>
        </div>
      )}
    </BodyShell>
  )
}
