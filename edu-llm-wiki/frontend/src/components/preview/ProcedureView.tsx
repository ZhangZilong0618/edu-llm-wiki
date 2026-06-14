/**
 * Procedure page view (A 组基础页).
 *
 * Surfaces the standard `## 目标 / 输入 / 输出 / 步骤 / 检查清单` sections
 * from the body into a structured grid.
 */
import { BodyShell } from "./BodyShell"
import { Card, MarkdownSlice } from "./Card"
import { extractSection } from "@/lib/page-sections"
import type { WikiPage } from "@/types/wiki"

export function ProcedureView({ page }: { page: WikiPage }) {
  const goal = extractSection(page.content, ["目标", "Goal"])
  const inputs = extractSection(page.content, ["输入", "Inputs"])
  const outputs = extractSection(page.content, ["输出", "Outputs"])
  const steps = extractSection(page.content, ["步骤", "Steps"])
  const checklist = extractSection(page.content, ["检查清单", "Checklist"])

  return (
    <BodyShell
      page={page}
      tagClassName="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-600 dark:bg-emerald-950/30"
    >
      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        {goal && (
          <Card title="目标 / Goal" accent="text-emerald-600" className="sm:col-span-2">
            <MarkdownSlice markdown={goal} />
          </Card>
        )}
        {inputs && (
          <Card title="输入 / Inputs" accent="text-emerald-600">
            <MarkdownSlice markdown={inputs} />
          </Card>
        )}
        {outputs && (
          <Card title="输出 / Outputs" accent="text-emerald-600">
            <MarkdownSlice markdown={outputs} />
          </Card>
        )}
        {steps && (
          <Card title="步骤 / Steps" accent="text-emerald-600" className="sm:col-span-2">
            <MarkdownSlice markdown={steps} />
          </Card>
        )}
        {checklist && (
          <Card title="检查清单 / Checklist" accent="text-emerald-600" className="sm:col-span-2">
            <MarkdownSlice markdown={checklist} />
          </Card>
        )}
      </div>
    </BodyShell>
  )
}
