/**
 * Source page view.
 *
 * A "source" page is an index/summary of an original document. We surface
 * the first paragraph of the body as a "Summary" summary card. Tags and source
 * pills are still rendered by `BodyShell`.
 */
import { BodyShell } from "./BodyShell"
import { Card } from "./Card"
import { firstParagraph } from "@/lib/page-sections"
import type { WikiPage } from "@/types/wiki"

export function SourceView({ page }: { page: WikiPage }) {
  const summary = firstParagraph(page.content)
  return (
    <BodyShell
      page={page}
      tagClassName="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600 dark:bg-gray-800"
    >
      {summary && (
        <div className="mb-3">
          <Card title="Summary" accent="text-gray-600">
            <p className="text-[13px] leading-relaxed">{summary}</p>
          </Card>
        </div>
      )}
    </BodyShell>
  )
}
