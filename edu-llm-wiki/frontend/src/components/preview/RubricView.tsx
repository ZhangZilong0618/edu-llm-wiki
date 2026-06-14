/**
 * Rubric page view (C 组评价页).
 *
 * 掌握等级 + 表现描述 + 评分规则。表格化展示。
 */
import { BodyShell } from "./BodyShell"
import { Card, Bullets, MarkdownSlice } from "./Card"
import { extractSection } from "@/lib/page-sections"
import type { WikiPage } from "@/types/wiki"

export function RubricView({ page }: { page: WikiPage }) {
  const levels = extractSection(page.content, ["掌握等级", "Levels"])
  const criteria = extractSection(page.content, ["评分规则", "Criteria"])
  const rubricDescription = extractSection(page.content, ["表现描述", "Descriptors"])

  return (
    <BodyShell
      page={page}
      tagClassName="rounded bg-rose-50 px-1.5 py-0.5 text-[10px] text-rose-600 dark:bg-rose-950/30"
    >
      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        {levels && (
          <Card title="掌握等级 / Levels" accent="text-rose-600" className="sm:col-span-2">
            <MarkdownSlice markdown={levels} />
          </Card>
        )}
        {rubricDescription && (
          <Card title="表现描述 / Descriptors" accent="text-rose-600">
            <MarkdownSlice markdown={rubricDescription} />
          </Card>
        )}
        {criteria && (
          <Card title="评分规则 / Criteria" accent="text-rose-600">
            <MarkdownSlice markdown={criteria} />
          </Card>
        )}
      </div>
    </BodyShell>
  )
}
