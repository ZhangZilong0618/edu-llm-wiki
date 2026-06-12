import type { WikiPage } from "@/types/wiki"
import { BodyShell } from "./BodyShell"

export function SourceView({ page }: { page: WikiPage }) {
  return <BodyShell page={page} tagClassName="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600 dark:bg-gray-800" />
}
