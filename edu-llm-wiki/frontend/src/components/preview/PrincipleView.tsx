/**
 * Principle page view.
 *
 * Per docs/wiki-redesign.md §4.2 the top of a principle page shows four
 * structured cards: "陈述" (statement), "适用条件" (conditions), "推导/说明"
 * (proof sketch), and "应用" (applications). All parsed from body `##`
 * sections.
 */
import { BodyShell } from "./BodyShell"
import { Card, MarkdownSlice } from "./Card"
import { extractSection } from "@/lib/page-sections"
import type { WikiPage } from "@/types/wiki"

export function PrincipleView({ page }: { page: WikiPage }) {
  const statement = extractSection(page.content, ["陈述", "Statement"])
  const conditions = extractSection(page.content, ["适用条件", "Conditions"])
  const proof = extractSection(page.content, ["推导/说明", "推导", "Proof"])
  const applications = extractSection(page.content, ["应用", "Applications"])

  return (
    <BodyShell
      page={page}
      tagClassName="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-600 dark:bg-amber-950/30"
    >
      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        {statement && (
          <Card title="陈述 / Statement" accent="text-amber-600" className="sm:col-span-2">
            <MarkdownSlice markdown={statement} />
          </Card>
        )}
        {conditions && (
          <Card title="适用条件 / Conditions" accent="text-amber-600">
            <MarkdownSlice markdown={conditions} />
          </Card>
        )}
        {proof && (
          <Card title="推导/说明 / Proof sketch" accent="text-amber-600">
            <MarkdownSlice markdown={proof} />
          </Card>
        )}
        {applications && (
          <Card title="应用 / Applications" accent="text-amber-600" className="sm:col-span-2">
            <MarkdownSlice markdown={applications} />
          </Card>
        )}
      </div>
    </BodyShell>
  )
}
