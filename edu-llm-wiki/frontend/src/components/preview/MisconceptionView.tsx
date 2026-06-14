/**
 * Misconception page view (B 组应用页).
 *
 * 错误说法 / 正确理解 / 诊断题 三段对比，遵循 v2 schema 的
 * `common_misconceptions` 字段命名以保证字段复用。
 */
import { BodyShell } from "./BodyShell"
import { Card, MarkdownSlice } from "./Card"
import { extractSection } from "@/lib/page-sections"
import type { WikiPage } from "@/types/wiki"

export function MisconceptionView({ page }: { page: WikiPage }) {
  const wrong = extractSection(page.content, ["错误说法", "Wrong claim", "Misconception"])
  const right = extractSection(page.content, ["正确理解", "Correct understanding", "Right"])
  const diagnostic = extractSection(page.content, ["诊断题", "Diagnostic"])

  return (
    <BodyShell
      page={page}
      tagClassName="rounded bg-rose-50 px-1.5 py-0.5 text-[10px] text-rose-600 dark:bg-rose-950/30"
    >
      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        {wrong && (
          <Card title="错误说法 / Wrong claim" accent="text-rose-600" className="sm:col-span-2">
            <MarkdownSlice markdown={wrong} />
          </Card>
        )}
        {right && (
          <Card title="正确理解 / Correct understanding" accent="text-emerald-600" className="sm:col-span-2">
            <MarkdownSlice markdown={right} />
          </Card>
        )}
        {diagnostic && (
          <Card title="诊断题 / Diagnostic" accent="text-rose-600" className="sm:col-span-2">
            <MarkdownSlice markdown={diagnostic} />
          </Card>
        )}
      </div>
    </BodyShell>
  )
}
