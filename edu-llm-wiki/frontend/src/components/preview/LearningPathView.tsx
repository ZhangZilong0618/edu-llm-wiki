/**
 * Learning Path page view (C 组整合页).
 *
 * 列表型页：先修知识 / 推荐顺序 / 检测点。这一类不引文，因为它的内容
 * 是"指向其他页"，重复引文没意义。
 */
import { BodyShell } from "./BodyShell"
import { Card, Bullets, MarkdownSlice } from "./Card"
import { extractSection } from "@/lib/page-sections"
import { useAppStore } from "@/stores/app-store"
import { displayWikiTitle } from "@/lib/wiki-title"
import type { WikiPage } from "@/types/wiki"

export function LearningPathView({ page }: { page: WikiPage }) {
  const prerequisites = extractSection(page.content, ["先修知识", "Prerequisites"])
  const order = extractSection(page.content, ["推荐顺序", "Recommended order"])
  const checkpoints = extractSection(page.content, ["检测点", "Checkpoints"])
  const wikiPages = useAppStore((s) => s.wikiPages)
  const selectPage = useAppStore((s) => s.selectPage)

  // Render prerequisites as clickable chips linking to other wiki pages.
  const prereqPaths = (page.prerequisites ?? []).map((p) => p.replace(/\.md$/, ""))
  const prereqChips = prereqPaths
    .map((pp) => wikiPages.find((w) => w.path.replace(/\.md$/, "") === pp))
    .filter((w): w is NonNullable<typeof w> => Boolean(w))

  return (
    <BodyShell
      page={page}
      tagClassName="rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] text-indigo-600 dark:bg-indigo-950/30"
    >
      {prereqChips.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1.5">
          <span className="text-[10px] uppercase tracking-wider text-[var(--muted-foreground)]">
            先修：
          </span>
          {prereqChips.map((w) => (
            <button
              key={w.path}
              onClick={() => selectPage(w.path)}
              className="rounded bg-indigo-50 px-2 py-0.5 text-[11px] text-indigo-600 hover:underline dark:bg-indigo-950/30"
            >
              {displayWikiTitle(w)}
            </button>
          ))}
        </div>
      )}
      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        {prerequisites && (
          <Card title="先修知识 / Prerequisites" accent="text-indigo-600" className="sm:col-span-2">
            <MarkdownSlice markdown={prerequisites} />
          </Card>
        )}
        {order && (
          <Card title="推荐顺序 / Recommended order" accent="text-indigo-600" className="sm:col-span-2">
            <MarkdownSlice markdown={order} />
          </Card>
        )}
        {checkpoints && (
          <Card title="检测点 / Checkpoints" accent="text-indigo-600" className="sm:col-span-2">
            <MarkdownSlice markdown={checkpoints} />
          </Card>
        )}
      </div>
    </BodyShell>
  )
}
