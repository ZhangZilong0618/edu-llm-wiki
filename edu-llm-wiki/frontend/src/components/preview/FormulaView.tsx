import type { WikiPage } from "@/types/wiki"
import { BodyShell } from "./BodyShell"

export function FormulaView({ page }: { page: WikiPage }) {
  return <BodyShell page={page} tagClassName="rounded bg-violet-50 px-1.5 py-0.5 text-[10px] text-violet-600 dark:bg-violet-950/30" />
}
