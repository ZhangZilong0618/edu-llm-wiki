/**
 * Example page view (B 组应用页).
 *
 * Pulls out `## 题目 / 步骤 / 答案 / 变式` sections. B 组页是可选生成的，
 * UI 上不区分"是否 B 组"——预览时跟 A 组同样的卡片式结构。
 */
import { BodyShell } from "./BodyShell"
import { Card, MarkdownSlice } from "./Card"
import { extractSection } from "@/lib/page-sections"
import type { WikiPage } from "@/types/wiki"

export function ExampleView({ page }: { page: WikiPage }) {
  const problem = extractSection(page.content, ["题目", "问题", "Problem"])
  const steps = extractSection(page.content, ["步骤", "解法", "Steps"])
  const answer = extractSection(page.content, ["答案", "Answer"])
  const variants = extractSection(page.content, ["变式", "Variants"])

  return (
    <BodyShell
      page={page}
      tagClassName="rounded bg-teal-50 px-1.5 py-0.5 text-[10px] text-teal-600 dark:bg-teal-950/30"
    >
      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        {problem && (
          <Card title="题目 / Problem" accent="text-teal-600" className="sm:col-span-2">
            <MarkdownSlice markdown={problem} />
          </Card>
        )}
        {steps && (
          <Card title="步骤 / Steps" accent="text-teal-600">
            <MarkdownSlice markdown={steps} />
          </Card>
        )}
        {answer && (
          <Card title="答案 / Answer" accent="text-teal-600">
            <MarkdownSlice markdown={answer} />
          </Card>
        )}
        {variants && (
          <Card title="变式 / Variants" accent="text-teal-600" className="sm:col-span-2">
            <MarkdownSlice markdown={variants} />
          </Card>
        )}
      </div>
    </BodyShell>
  )
}
