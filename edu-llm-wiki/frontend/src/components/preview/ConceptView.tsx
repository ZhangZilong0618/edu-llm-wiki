/**
 * Concept page view.
 *
 * Per docs/wiki-redesign.md §4.2 the top of a concept page should show an
 * "易混淆 / common misconceptions" card. We pull this from the structured
 * `common_misconceptions` frontmatter (the only v2 field that has a clean
 * per-type mapping today). Everything else flows through the shared
 * `BodyShell` markdown body.
 */
import { BodyShell } from "./BodyShell"
import { Card, Bullets } from "./Card"
import type { WikiPage } from "@/types/wiki"

export function ConceptView({ page }: { page: WikiPage }) {
  const misconceptions = page.common_misconceptions ?? []
  return (
    <BodyShell
      page={page}
      tagClassName="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-600 dark:bg-blue-950/30"
    >
      {misconceptions.length > 0 && (
        <div className="mb-3">
          <Card title="易混淆 / Common misconceptions" accent="text-blue-600">
            <Bullets items={misconceptions} />
          </Card>
        </div>
      )}
    </BodyShell>
  )
}
