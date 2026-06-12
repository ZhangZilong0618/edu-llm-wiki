import type { WikiPage } from "@/types/wiki"
import { BodyShell } from "./BodyShell"

export function SynthesisView({ page }: { page: WikiPage }) {
  return <BodyShell page={page} tagClassName="rounded bg-pink-50 px-1.5 py-0.5 text-[10px] text-pink-600 dark:bg-pink-950/30" />
}
