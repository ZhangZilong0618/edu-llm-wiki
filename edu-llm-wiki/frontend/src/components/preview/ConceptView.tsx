import type { WikiPage } from "@/types/wiki"
import { BodyShell } from "./BodyShell"

export function ConceptView({ page }: { page: WikiPage }) {
  return <BodyShell page={page} tagClassName="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-600 dark:bg-blue-950/30" />
}
