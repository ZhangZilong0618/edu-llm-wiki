import type { WikiPage } from "@/types/wiki"
import { BodyShell } from "./BodyShell"

export function PrincipleView({ page }: { page: WikiPage }) {
  return <BodyShell page={page} tagClassName="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-600 dark:bg-amber-950/30" />
}
