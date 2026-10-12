/**
 * Procedure page view (A 组Basics page).
 *
 * Surfaces the standard `## Goal / Input / Output / Steps / Checklist` sections
 * from the body into a structured grid.
 */
import { BodyShell } from "./BodyShell"
import { Card, MarkdownSlice } from "./Card"
import { extractSection } from "@/lib/page-sections"
import type { WikiPage } from "@/types/wiki"

export function ProcedureView({ page }: { page: WikiPage }) {
  const goal = extractSection(page.content, ["Objective", "Goal"])
  const inputs = extractSection(page.content, ["Input", "Inputs"])
  const outputs = extractSection(page.content, ["Output", "Outputs"])
  const steps = extractSection(page.content, ["Steps", "Steps"])
  const checklist = extractSection(page.content, ["Checklist", "Checklist"])

  return (
    <BodyShell
      page={page}
      tagClassName="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-600 dark:bg-emerald-950/30"
    >
      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        {goal && (
          <Card title="Goal" accent="text-emerald-600" className="sm:col-span-2">
            <MarkdownSlice markdown={goal} />
          </Card>
        )}
        {inputs && (
          <Card title="Inputs" accent="text-emerald-600">
            <MarkdownSlice markdown={inputs} />
          </Card>
        )}
        {outputs && (
          <Card title="Outputs" accent="text-emerald-600">
            <MarkdownSlice markdown={outputs} />
          </Card>
        )}
        {steps && (
          <Card title="Steps" accent="text-emerald-600" className="sm:col-span-2">
            <MarkdownSlice markdown={steps} />
          </Card>
        )}
        {checklist && (
          <Card title="Checklist" accent="text-emerald-600" className="sm:col-span-2">
            <MarkdownSlice markdown={checklist} />
          </Card>
        )}
      </div>
    </BodyShell>
  )
}
