/**
 * Formula page view.
 *
 * Per docs/wiki-redesign.md §4.2 the top of a formula page shows three
 * structured cards: "Formula" (statement), "Variable Description" (variables), and
 * "Use Cases" (applicability). Each is parsed from the page body's `##`
 * section so we don't need to promote the v2 design fields to frontmatter
 * in this round. Sections that don't exist collapse silently.
 */
import { BodyShell } from "./BodyShell"
import { Card, MarkdownSlice } from "./Card"
import { extractSection } from "@/lib/page-sections"
import type { WikiPage } from "@/types/wiki"

export function FormulaView({ page }: { page: WikiPage }) {
  const statement = extractSection(page.content, ["Formula", "Formula", "Statement"])
  const variables = extractSection(page.content, ["Variable Description", "Variable", "Variables"])
  const applicability = extractSection(page.content, [
    "Use Cases",
    "Applicable Conditions",
    "Applicability",
    "Applicable Boundaries",
  ])

  return (
    <BodyShell
      page={page}
      tagClassName="rounded bg-violet-50 px-1.5 py-0.5 text-[10px] text-violet-600 dark:bg-violet-950/30"
    >
      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        {statement && (
          <Card title="Formula" accent="text-violet-600" className="sm:col-span-2">
            <MarkdownSlice markdown={statement} />
          </Card>
        )}
        {variables && (
          <Card title="Variables" accent="text-violet-600">
            <MarkdownSlice markdown={variables} />
          </Card>
        )}
        {applicability && (
          <Card title="Applicability" accent="text-violet-600">
            <MarkdownSlice markdown={applicability} />
          </Card>
        )}
      </div>
    </BodyShell>
  )
}
