/**
 * Formula page view.
 *
 * Per docs/wiki-redesign.md §4.2 the top of a formula page shows three
 * structured cards: "公式" (statement), "变量说明" (variables), and
 * "适用场景" (applicability). Each is parsed from the page body's `##`
 * section so we don't need to promote the v2 design fields to frontmatter
 * in this round. Sections that don't exist collapse silently.
 */
import { BodyShell } from "./BodyShell"
import { Card, MarkdownSlice } from "./Card"
import { extractSection } from "@/lib/page-sections"
import type { WikiPage } from "@/types/wiki"

export function FormulaView({ page }: { page: WikiPage }) {
  const statement = extractSection(page.content, ["公式", "Formula", "Statement"])
  const variables = extractSection(page.content, ["变量说明", "变量", "Variables"])
  const applicability = extractSection(page.content, [
    "适用场景",
    "适用条件",
    "Applicability",
    "适用边界",
  ])

  return (
    <BodyShell
      page={page}
      tagClassName="rounded bg-violet-50 px-1.5 py-0.5 text-[10px] text-violet-600 dark:bg-violet-950/30"
    >
      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        {statement && (
          <Card title="公式 / Formula" accent="text-violet-600" className="sm:col-span-2">
            <MarkdownSlice markdown={statement} />
          </Card>
        )}
        {variables && (
          <Card title="变量说明 / Variables" accent="text-violet-600">
            <MarkdownSlice markdown={variables} />
          </Card>
        )}
        {applicability && (
          <Card title="适用场景 / Applicability" accent="text-violet-600">
            <MarkdownSlice markdown={applicability} />
          </Card>
        )}
      </div>
    </BodyShell>
  )
}
