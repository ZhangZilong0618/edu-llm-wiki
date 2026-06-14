/**
 * Learning Objective page view (C 组评价页).
 *
 * 行为动词 + 认知层级（Blooms）+ 达成证据。
 */
import { BodyShell } from "./BodyShell"
import { Card, Bullets, MarkdownSlice } from "./Card"
import { extractSection } from "@/lib/page-sections"
import type { WikiPage } from "@/types/wiki"

export function LearningObjectiveView({ page }: { page: WikiPage }) {
  const verbs = extractSection(page.content, ["行为动词", "Action verbs"])
  const level = extractSection(page.content, ["认知层级", "Blooms level"])
  const evidence = extractSection(page.content, ["达成证据", "Evidence"])
  const items = (verbs ?? "")
    .split(/\n+/)
    .map((s) => s.replace(/^[-*•\s]+/, "").trim())
    .filter(Boolean)

  return (
    <BodyShell
      page={page}
      tagClassName="rounded bg-purple-50 px-1.5 py-0.5 text-[10px] text-purple-600 dark:bg-purple-950/30"
    >
      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        {items.length > 0 && (
          <Card title="行为动词 / Action verbs" accent="text-purple-600">
            <Bullets items={items} />
          </Card>
        )}
        {level && (
          <Card title="认知层级 / Blooms" accent="text-purple-600">
            <MarkdownSlice markdown={level} />
          </Card>
        )}
        {evidence && (
          <Card title="达成证据 / Evidence of mastery" accent="text-purple-600" className="sm:col-span-2">
            <MarkdownSlice markdown={evidence} />
          </Card>
        )}
      </div>
    </BodyShell>
  )
}
