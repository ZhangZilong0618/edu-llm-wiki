/**
 * Example page view (B 组Application page).
 *
 * Pulls out `## Question / Steps / Answer / Variants` sections. B 组页是可选生成的，
 * UI 上不区分"Is Group B"——Preview时跟 A 组同样的卡片式结构。
 */
import { BodyShell } from "./BodyShell"
import { Card, MarkdownSlice } from "./Card"
import { extractSection } from "@/lib/page-sections"
import type { WikiPage } from "@/types/wiki"

export function ExampleView({ page }: { page: WikiPage }) {
  const problem = extractSection(page.content, ["Question", "Question", "Problem"])
  const steps = extractSection(page.content, ["Steps", "Solution", "Steps"])
  const answer = extractSection(page.content, ["Answer", "Answer"])
  const variants = extractSection(page.content, ["Variation", "Variants"])

  return (
    <BodyShell
      page={page}
      tagClassName="rounded bg-teal-50 px-1.5 py-0.5 text-[10px] text-teal-600 dark:bg-teal-950/30"
    >
      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        {problem && (
          <Card title="Problem" accent="text-teal-600" className="sm:col-span-2">
            <MarkdownSlice markdown={problem} />
          </Card>
        )}
        {steps && (
          <Card title="Steps" accent="text-teal-600">
            <MarkdownSlice markdown={steps} />
          </Card>
        )}
        {answer && (
          <Card title="Answer" accent="text-teal-600">
            <MarkdownSlice markdown={answer} />
          </Card>
        )}
        {variants && (
          <Card title="Variants" accent="text-teal-600" className="sm:col-span-2">
            <MarkdownSlice markdown={variants} />
          </Card>
        )}
      </div>
    </BodyShell>
  )
}
