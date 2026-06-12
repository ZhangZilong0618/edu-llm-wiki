import { Markdown } from "@/components/markdown"
import type { WikiPage } from "@/types/wiki"
import { FrontmatterCards } from "./FrontmatterCards"

export function BodyShell({
  page,
  tagClassName,
  children,
}: {
  page: WikiPage
  tagClassName?: string
  children?: React.ReactNode
}) {
  return (
    <div>
      {page.tags.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1">
          {page.tags.map((t) => (
            <span
              key={t}
              className={
                tagClassName ??
                "rounded bg-[var(--muted)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]"
              }
            >
              #{t}
            </span>
          ))}
        </div>
      )}
      {children}
      <Markdown>{page.content || "*No content*"}</Markdown>
      <FrontmatterCards page={page} />
      {page.sources.length > 0 && (
        <div className="mt-4 text-[10px] text-[var(--muted-foreground)]">
          出处：{page.sources.join(" · ")}
        </div>
      )}
    </div>
  )
}
