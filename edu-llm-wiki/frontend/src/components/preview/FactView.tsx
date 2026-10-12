/**
 * Fact page view — 单点为真的具体陈述（常数、具体物质数据、约定阈值）。
 * 事实页没有概念页那样的专用 frontmatter 卡片，直接走共享 BodyShell。
 */
import { BodyShell } from "./BodyShell"
import type { WikiPage } from "@/types/wiki"

export function FactView({ page }: { page: WikiPage }) {
  return (
    <BodyShell
      page={page}
      tagClassName="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-600 dark:bg-emerald-950/30"
    />
  )
}
